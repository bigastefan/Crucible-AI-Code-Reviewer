<!-- version: 1.0 | project: Focus Web (Angular) -->

- Keep API calls in services, not components — flag HttpClient used directly in a component.
- Flag business logic in templates; it belongs in the component or a pipe.
- New shared UI components need a corresponding spec. Flag if missing.
- Flag hard-coded API base URLs or environment values; use the environment config.
- Flag user-supplied values rendered without sanitization (XSS via [innerHTML]).
