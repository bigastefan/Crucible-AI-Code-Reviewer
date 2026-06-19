<!-- version: 1.0 | project: Crucible Golden-PR test repo -->

- This repo exists to exercise Crucible's Golden PRs (GP-01–10). Review changed lines normally.
- Flag null/undefined dereferences and off-by-one errors in changed code.
- Flag any SQL built by string concatenation of inputs (require parameterization).
- Flag hard-coded secrets, keys, or connection strings.
