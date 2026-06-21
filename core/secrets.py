"""Secret detection + redaction. Host- and model-neutral; runs in core BEFORE the
diff leaves the process (so it protects BOTH the Azure and GitHub paths).

Two decoupled jobs over the SAME pattern set:
  - mask_secrets(text)        → scrub every secret-looking substring from the OUTBOUND
                                diff text (what prompt_builder/llm see). The value never
                                reaches the model.
  - find_secret_findings(files) → scan PARSED added lines so each hit gets a precise
                                file:line, raised as a CRITICAL / SECURITY finding.

NON-NEGOTIABLE: the secret VALUE is never returned in a finding, logged, or echoed —
only its KIND and location. Patterns below are deliberately specific to avoid nuking
ordinary code; tune here.
"""
from __future__ import annotations

import re
from typing import List, Set, Tuple

from core.diff import ADDED, FileDiff
from core.models import Category, Finding, Severity

# (kind, compiled_regex, secret_group)
#   secret_group == 0 → the whole match is the secret (replace all of it)
#   secret_group == N → only group N is the secret (keep the prefix/suffix context)
_PATTERNS: List[Tuple[str, "re.Pattern", int]] = [
    ("aws_access_key_id", re.compile(r"AKIA[0-9A-Z]{16}"), 0),
    ("private_key_block", re.compile(
        r"-----BEGIN[A-Z ]*PRIVATE KEY-----.*?-----END[A-Z ]*PRIVATE KEY-----", re.DOTALL), 0),
    ("private_key_marker", re.compile(r"-----BEGIN[A-Z ]*PRIVATE KEY-----"), 0),
    ("api_key_sk", re.compile(r"sk-[A-Za-z0-9_\-]{20,}"), 0),
    ("github_token", re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"), 0),
    ("slack_token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"), 0),
    ("google_api_key", re.compile(r"AIza[0-9A-Za-z_\-]{35}"), 0),
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"), 0),
    ("bearer_token", re.compile(r"(?i)(bearer\s+)([A-Za-z0-9_\-\.=]{16,})"), 2),
    ("secret_assignment", re.compile(
        r"(?i)((?:api[_-]?key|secret|token|access[_-]?key|client[_-]?secret|passwd|password|pwd)"
        r"\s*[:=]\s*['\"]?)([A-Za-z0-9_\-\./+]{12,})(['\"]?)"), 2),
    ("connection_password", re.compile(r"(?i)((?:password|pwd)\s*=\s*)([^;\s'\"]{6,})"), 2),
]


def mask_secrets(text: str) -> Tuple[str, Set[str]]:
    """Return (masked_text, kinds_found). Every detected secret is replaced with
    ``***REDACTED:<kind>***``; surrounding context (e.g. ``password=``) is preserved."""
    kinds: Set[str] = set()
    masked = text or ""
    for kind, rx, group in _PATTERNS:
        def _repl(m, kind=kind, group=group):
            kinds.add(kind)
            token = f"***REDACTED:{kind}***"
            if group == 0:
                return token
            return m.group(0).replace(m.group(group), token, 1)

        masked = rx.sub(_repl, masked)
    return masked, kinds


def find_secret_findings(files: List[FileDiff]) -> List[Finding]:
    """Scan added (right-side) lines and raise each secret as a CRITICAL / SECURITY
    finding anchored to its line. The value is NEVER included."""
    findings: List[Finding] = []
    seen: Set[Tuple[str, int]] = set()  # one finding per (file, line) — avoid stacking
    for fd in files:
        for hunk in fd.hunks:
            for ln in hunk.lines:
                if ln.kind != ADDED or ln.right_line is None:
                    continue
                if (fd.path, ln.right_line) in seen:
                    continue
                for kind, rx, _ in _PATTERNS:
                    if kind == "private_key_block":
                        continue  # multi-line; the marker variant catches the start line
                    if rx.search(ln.content):
                        seen.add((fd.path, ln.right_line))
                        findings.append(Finding(
                            file=fd.path,
                            line=ln.right_line,
                            severity=Severity.CRITICAL,
                            category=Category.SECURITY,
                            title=f"Hardcoded secret detected ({kind})",
                            comment=(
                                "A value matching a known secret pattern was found on this "
                                "changed line. Remove it from source and **rotate the credential**; "
                                "load it from a secret store or environment variable instead. "
                                "(Crucible redacted the value before sending the diff to the model.)"
                            ),
                            suggestion=None,
                        ))
                        break  # one finding per line
    return findings
