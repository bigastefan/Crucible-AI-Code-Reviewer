"""Unified-diff parser → files → hunks → exact right-side (new-file) line numbers.

★ The load-bearing module (Delivery Plan §10). Wrong-line comments are worse than
none, and GitHub's review API REJECTS any comment not anchored to a real right-side
diff line — so this parser is what makes BOTH adapters correct (gap X-04).

Design boundary: this module is PURE (string in → model out). It never runs git and
never names a host — `providers/*.get_diff()` owns the git invocation + ref
normalization and hands the raw unified diff here.

Anchoring rule: only ADDED lines are commentable. A changed line appears as a
removed + an added line; we anchor on the added (right) side. Context lines carry a
right_line for range math but are not commentable ("flag only lines that changed").
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from fnmatch import fnmatch
from typing import List, Optional, Set

# kinds of body lines within a hunk
CONTEXT = "context"
ADDED = "added"
REMOVED = "removed"

# change_type values
ADDED_FILE = "added"
MODIFIED = "modified"
DELETED = "deleted"
RENAMED = "renamed"
COPIED = "copied"
MODE_CHANGED = "mode_changed"

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_DIFF_GIT_PREFIX = "diff --git "


@dataclass
class DiffLine:
    kind: str  # CONTEXT | ADDED | REMOVED
    content: str  # line text without the leading +/-/space marker
    right_line: Optional[int]  # new-file line number; None for REMOVED lines


@dataclass
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: List[DiffLine] = field(default_factory=list)

    @property
    def added_lines(self) -> List[DiffLine]:
        return [ln for ln in self.lines if ln.kind == ADDED]


@dataclass
class FileDiff:
    old_path: Optional[str]
    new_path: Optional[str]
    change_type: str
    hunks: List[Hunk] = field(default_factory=list)
    is_binary: bool = False

    @property
    def path(self) -> str:
        """The path to anchor comments / match rules against: the new path, except
        for deletions (no new path) where we fall back to the old path."""
        return self.new_path or self.old_path or ""

    @property
    def added_line_numbers(self) -> Set[int]:
        """Right-side line numbers a comment may be anchored to."""
        nums: Set[int] = set()
        for h in self.hunks:
            for ln in h.added_lines:
                if ln.right_line is not None:
                    nums.add(ln.right_line)
        return nums

    def is_commentable_line(self, line_no: int) -> bool:
        return line_no in self.added_line_numbers


# --------------------------------------------------------------------------- #
# path helpers
# --------------------------------------------------------------------------- #
def _unquote(token: str) -> str:
    """Git quotes paths with special chars in C-style double quotes. Minimal decode."""
    if len(token) >= 2 and token.startswith('"') and token.endswith('"'):
        inner = token[1:-1]
        try:
            return inner.encode("latin-1", "backslashreplace").decode("unicode_escape")
        except Exception:
            return inner
    return token


def _strip_ab(path: str) -> str:
    if path[:2] in ("a/", "b/"):
        return path[2:]
    return path


def _parse_marker_path(raw: str) -> Optional[str]:
    """Parse the path from a '--- ' / '+++ ' line body. Returns None for /dev/null."""
    # git appends a TAB to delimit paths that contain spaces -> drop it.
    if "\t" in raw:
        raw = raw.split("\t", 1)[0]
    raw = raw.strip()
    raw = _unquote(raw)
    if raw == "/dev/null":
        return None
    return _strip_ab(raw)


def _parse_diff_git_paths(line: str) -> tuple[Optional[str], Optional[str]]:
    """Fallback path source (used for binary/mode/rename where ---/+++ are absent)."""
    rest = line[len(_DIFF_GIT_PREFIX):].rstrip("\n")
    if rest.startswith('"'):
        # two quoted tokens: "a/..." "b/..."
        m = re.match(r'^("(?:[^"\\]|\\.)*")\s+("(?:[^"\\]|\\.)*")$', rest)
        if m:
            return _strip_ab(_unquote(m.group(1))), _strip_ab(_unquote(m.group(2)))
    # Unquoted. Paths may contain spaces, so we can't naively split. The reliable
    # split point is " b/" when the left path starts with "a/".
    if rest.startswith("a/") and " b/" in rest:
        idx = rest.find(" b/")
        return _strip_ab(rest[:idx]), _strip_ab(rest[idx + 1:])
    parts = rest.split(" ")
    if len(parts) >= 2:
        return _strip_ab(parts[0]), _strip_ab(parts[-1])
    return None, None


# --------------------------------------------------------------------------- #
# parser
# --------------------------------------------------------------------------- #
class _FileBuilder:
    def __init__(self):
        self.old_path: Optional[str] = None
        self.new_path: Optional[str] = None
        self.git_old: Optional[str] = None
        self.git_new: Optional[str] = None
        self.saw_minus = False
        self.saw_plus = False
        self.is_binary = False
        self.is_deleted = False
        self.is_new = False
        self.is_rename = False
        self.is_copy = False
        self.saw_mode = False
        self.hunks: List[Hunk] = []

    def finalize(self) -> FileDiff:
        old = self.old_path if self.saw_minus else self.git_old
        new = self.new_path if self.saw_plus else self.git_new
        # /dev/null (None) is authoritative when the marker was seen.
        if self.saw_minus:
            old = self.old_path
        if self.saw_plus:
            new = self.new_path

        if self.is_rename:
            change = RENAMED
        elif self.is_copy:
            change = COPIED
        elif self.is_deleted:
            change = DELETED
        elif self.is_new:
            change = ADDED_FILE
        elif not self.hunks and not self.is_binary and self.saw_mode:
            change = MODE_CHANGED
        else:
            change = MODIFIED

        return FileDiff(
            old_path=old,
            new_path=new,
            change_type=change,
            hunks=self.hunks,
            is_binary=self.is_binary,
        )


def parse_diff(text: str) -> List[FileDiff]:
    """Parse a full unified diff (one or more `diff --git` sections) into FileDiffs."""
    files: List[FileDiff] = []
    builder: Optional[_FileBuilder] = None
    current_hunk: Optional[Hunk] = None
    new_cursor = 0
    old_cursor = 0

    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]

        if line.startswith(_DIFF_GIT_PREFIX):
            if builder is not None:
                files.append(builder.finalize())
            builder = _FileBuilder()
            current_hunk = None
            builder.git_old, builder.git_new = _parse_diff_git_paths(line)
            i += 1
            continue

        if builder is None:
            # Tolerate a bare diff with no `diff --git` header (raw `---/+++/@@`).
            builder = _FileBuilder()
            current_hunk = None

        m = _HUNK_RE.match(line)
        if m:
            old_start = int(m.group(1))
            old_count = int(m.group(2)) if m.group(2) is not None else 1
            new_start = int(m.group(3))
            new_count = int(m.group(4)) if m.group(4) is not None else 1
            current_hunk = Hunk(old_start, old_count, new_start, new_count)
            builder.hunks.append(current_hunk)
            new_cursor = new_start
            old_cursor = old_start
            i += 1
            continue

        if current_hunk is not None and line[:1] in (" ", "+", "-", "\\"):
            marker = line[0]
            if marker == "\\":
                # "\ No newline at end of file" — metadata; advance nothing.
                i += 1
                continue
            content = line[1:]
            if marker == " ":
                current_hunk.lines.append(DiffLine(CONTEXT, content, new_cursor))
                new_cursor += 1
                old_cursor += 1
            elif marker == "+":
                current_hunk.lines.append(DiffLine(ADDED, content, new_cursor))
                new_cursor += 1
            elif marker == "-":
                current_hunk.lines.append(DiffLine(REMOVED, content, None))
                old_cursor += 1
            i += 1
            continue

        # Header / metadata line (current_hunk is None, or a blank line ending a hunk).
        current_hunk = None
        _parse_header_line(line, builder)
        i += 1

    if builder is not None:
        files.append(builder.finalize())
    return files


def _parse_header_line(line: str, b: _FileBuilder) -> None:
    if line.startswith("--- "):
        b.saw_minus = True
        b.old_path = _parse_marker_path(line[4:])
    elif line.startswith("+++ "):
        b.saw_plus = True
        b.new_path = _parse_marker_path(line[4:])
    elif line.startswith("deleted file mode"):
        b.is_deleted = True
    elif line.startswith("new file mode"):
        b.is_new = True
    elif line.startswith("rename from "):
        b.is_rename = True
        b.old_path = _strip_ab(_unquote(line[len("rename from "):].strip()))
        b.saw_minus = True
    elif line.startswith("rename to "):
        b.is_rename = True
        b.new_path = _strip_ab(_unquote(line[len("rename to "):].strip()))
        b.saw_plus = True
    elif line.startswith("copy from "):
        b.is_copy = True
        b.old_path = _strip_ab(_unquote(line[len("copy from "):].strip()))
        b.saw_minus = True
    elif line.startswith("copy to "):
        b.is_copy = True
        b.new_path = _strip_ab(_unquote(line[len("copy to "):].strip()))
        b.saw_plus = True
    elif line.startswith("old mode ") or line.startswith("new mode "):
        b.saw_mode = True
    elif line.startswith("Binary files ") or line.startswith("GIT binary patch"):
        b.is_binary = True
    # `index ...`, `similarity index ...`, `dissimilarity ...` → ignored.


# --------------------------------------------------------------------------- #
# exclude-path filtering (config-driven; applied before the LLM call)
# --------------------------------------------------------------------------- #
def is_excluded(path: str, patterns: List[str]) -> bool:
    """gitignore-ish matching for config `exclude_paths`. Supports `**`, `*`, `?`.
    A pattern with no slash matches the basename in any directory."""
    if not path:
        return False
    path = path.replace("\\", "/")
    base = path.rsplit("/", 1)[-1]
    for pat in patterns:
        pat = pat.replace("\\", "/")
        if "/" not in pat:
            if fnmatch(base, pat):
                return True
            continue
        if _glob_match(path, pat):
            return True
    return False


def _glob_match(path: str, pat: str) -> bool:
    regex = _glob_to_regex(pat)
    return re.match(regex, path) is not None


def _glob_to_regex(pat: str) -> str:
    out = ["^"]
    i = 0
    n = len(pat)
    while i < n:
        c = pat[i]
        if c == "*":
            if pat[i:i + 3] == "**/":
                out.append("(?:.*/)?")  # zero or more directories
                i += 3
                continue
            if pat[i:i + 2] == "**":
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    out.append("$")
    return "".join(out)


def filter_excluded(files: List[FileDiff], patterns: List[str]) -> List[FileDiff]:
    """Drop files whose anchor path matches an exclude pattern."""
    if not patterns:
        return list(files)
    return [f for f in files if not is_excluded(f.path, patterns)]
