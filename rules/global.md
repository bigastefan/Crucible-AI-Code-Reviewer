<!-- version: 1.0 | updated: 2026-06-19 -->

- Flag any hard-coded secret, API key, password, token, or connection string.
- Flag any `TODO`/`FIXME`/`HACK` left in production code paths.
- Flag broad `catch`/`except` blocks that swallow errors without handling or logging.
- Flag obviously dead or unreachable code introduced by the change.
- Flag missing input validation on data crossing a trust boundary (user input, request bodies).
- Flag changes that remove or weaken an existing test, auth check, or validation.
