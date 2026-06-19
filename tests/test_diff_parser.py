"""Phase 1 — the diff parser (T1-01). The headline assertion for every fixture is
"a comment for file X lands on right-side line N." Fixtures are AUTHENTIC git output
(generated with real `git diff`), so the parser is tested against what it actually meets.
"""
from pathlib import Path

import pytest

from core import diff as D
from core.diff import (
    FileDiff,
    filter_excluded,
    is_excluded,
    parse_diff,
)

FIX = Path(__file__).resolve().parent / "fixtures"


def load(name: str) -> str:
    return (FIX / name).read_text()


def parse(name: str):
    return parse_diff(load(name))


def by_path(files):
    return {f.path: f for f in files}


# --------------------------------------------------------------------------- #
# core edge cases — each asserts exact right-side line numbers
# --------------------------------------------------------------------------- #
def test_modify_two_hunks_right_lines():
    files = parse("modify.diff")
    assert len(files) == 1
    f = files[0]
    assert f.path == "calc.py"
    assert f.change_type == D.MODIFIED
    assert f.is_binary is False
    assert len(f.hunks) == 2
    # hunk 1: @@ -1,4 +1,5 @@   hunk 2: @@ -7,4 +8,5 @@
    assert (f.hunks[0].new_start, f.hunks[0].new_count) == (1, 5)
    assert (f.hunks[1].new_start, f.hunks[1].new_count) == (8, 5)
    # added right-side lines: "# validate inputs"=2, "result = a*b"=11, "return result"=12
    assert f.added_line_numbers == {2, 11, 12}
    assert f.is_commentable_line(2) and not f.is_commentable_line(1)


def test_added_file_all_lines_added():
    f = parse("add.diff")[0]
    assert f.change_type == D.ADDED_FILE
    assert f.old_path is None and f.new_path == "brand_new.py"
    assert f.added_line_numbers == {1, 2}


def test_deleted_file_has_no_commentable_lines():
    f = parse("delete.diff")[0]
    assert f.change_type == D.DELETED
    assert f.new_path is None
    assert f.path == "to_delete.py"  # falls back to old_path for anchoring/rules
    assert f.added_line_numbers == set()


def test_pure_rename_no_hunks():
    f = parse("rename.diff")[0]
    assert f.change_type == D.RENAMED
    assert f.old_path == "old_name.py" and f.new_path == "new_name.py"
    assert f.hunks == []
    assert f.added_line_numbers == set()


def test_rename_with_edit_anchors_on_new_path():
    f = parse("rename_edit.diff")[0]
    assert f.change_type == D.RENAMED
    assert f.old_path == "to_rename_edit.py" and f.new_path == "renamed_edited.py"
    assert f.added_line_numbers == {2}  # "return 100"


def test_binary_is_skipped_never_commentable():
    f = parse("binary.diff")[0]
    assert f.is_binary is True
    assert f.path == "logo.bin"
    assert f.hunks == []
    assert f.added_line_numbers == set()


def test_no_newline_at_eof_does_not_break_counting():
    f = parse("noeol.diff")[0]
    assert f.change_type == D.MODIFIED
    # "+line1 changed" is the only added line, at right-side line 1.
    assert f.added_line_numbers == {1}
    # the trailing context line is still counted correctly at line 2.
    ctx = [ln for h in f.hunks for ln in h.lines if ln.kind == D.CONTEXT]
    assert ctx[-1].right_line == 2 and ctx[-1].content == "line2 no newline"


def test_mode_only_change():
    f = parse("mode.diff")[0]
    assert f.change_type == D.MODE_CHANGED
    assert f.path == "script.sh"
    assert f.is_binary is False
    assert f.added_line_numbers == set()


def test_path_with_space_trailing_tab_stripped():
    f = parse("space_path.diff")[0]
    assert f.new_path == "with space.py"  # trailing tab + space handled
    assert f.added_line_numbers == {2}


def test_omitted_old_count_in_hunk_header():
    # space_path uses "@@ -1 +1,2 @@" (old count omitted -> defaults to 1).
    f = parse("space_path.diff")[0]
    assert (f.hunks[0].old_start, f.hunks[0].old_count) == (1, 1)
    assert (f.hunks[0].new_start, f.hunks[0].new_count) == (1, 2)


# --------------------------------------------------------------------------- #
# GP-07: binary + rename + delete (+ a normal modify) together → no crash
# --------------------------------------------------------------------------- #
def test_gp07_combo_no_crash_anchors_only_valid_lines():
    files = parse("gp07_combo.diff")
    assert len(files) == 4
    fmap = by_path(files)

    assert fmap["calc.py"].change_type == D.MODIFIED
    assert fmap["calc.py"].added_line_numbers == {2}  # "return a + b + 0"

    assert fmap["logo.bin"].is_binary is True
    assert fmap["logo.bin"].added_line_numbers == set()

    assert fmap["renamed2.py"].change_type == D.RENAMED
    assert fmap["renamed2.py"].added_line_numbers == set()

    assert fmap["to_delete.py"].change_type == D.DELETED
    assert fmap["to_delete.py"].added_line_numbers == set()

    # The ONLY commentable line in the whole diff is calc.py:2.
    commentable = {f.path: f.added_line_numbers for f in files if f.added_line_numbers}
    assert commentable == {"calc.py": {2}}


def test_empty_diff_returns_no_files():
    assert parse_diff("") == []


# --------------------------------------------------------------------------- #
# exclude-path filtering
# --------------------------------------------------------------------------- #
PATTERNS = ["**/*.min.js", "**/*.generated.cs", "**/Migrations/**", "package-lock.json", "**/dist/**"]


@pytest.mark.parametrize(
    "path,expected",
    [
        ("src/app/foo.min.js", True),
        ("foo.min.js", True),
        ("src/Db/Migrations/001_init.cs", True),
        ("Migrations/001.cs", True),
        ("frontend/package-lock.json", True),
        ("package-lock.json", True),
        ("build/dist/bundle.js", True),
        ("models/User.generated.cs", True),
        ("src/app/foo.ts", False),
        ("src/app/foo.js", False),
        ("docs/migrations.md", False),
    ],
)
def test_is_excluded(path, expected):
    assert is_excluded(path, PATTERNS) is expected


def test_filter_excluded_drops_matches():
    files = [
        FileDiff("a/x.min.js", "x.min.js", D.MODIFIED),
        FileDiff("a/keep.ts", "keep.ts", D.MODIFIED),
        FileDiff(None, "src/Migrations/2.cs", D.ADDED_FILE),
    ]
    kept = filter_excluded(files, PATTERNS)
    assert [f.path for f in kept] == ["keep.ts"]


# --------------------------------------------------------------------------- #
# cross-check our right-side line numbers against `unidiff` (if installed)
# --------------------------------------------------------------------------- #
def test_cross_check_against_unidiff():
    unidiff = pytest.importorskip("unidiff")
    for name in ["modify.diff", "add.diff", "rename_edit.diff", "noeol.diff", "space_path.diff"]:
        text = load(name)
        ours = {f.path: f.added_line_numbers for f in parse_diff(text)}
        patch = unidiff.PatchSet(text)
        for pf in patch:
            theirs = {
                ln.target_line_no
                for h in pf
                for ln in h
                if ln.is_added and ln.target_line_no is not None
            }
            path = pf.path  # unidiff strips the a//b/ prefix and resolves renames
            assert ours.get(path, set()) == theirs, f"{name}:{path} ours={ours.get(path)} unidiff={theirs}"
