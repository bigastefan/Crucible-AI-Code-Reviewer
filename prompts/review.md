<!-- version: 1.0 | updated: 2026-06-19 -->

Review this pull request.

## Global rules
{global_rules}

## Project rules — {project_name}
{project_rules}

## Language-specific rules
{language_rules}

## The diff
{diff}

---
Return ONE JSON object only, no prose, matching this shape:
{output_schema}

Severity guide:
- critical: security hole, data loss, crash, broken auth. Blocks merge.
- high: real bug or significant performance problem.
- medium: likely bug, missing test on new logic, risky pattern.
- low: maintainability / clarity. Optional.

Anchor every finding's `line` to a line that ACTUALLY CHANGED (an added/right-side line)
in the diff above. Do not comment on unchanged context lines.
