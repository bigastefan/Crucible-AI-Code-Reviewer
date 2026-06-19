<!-- version: 1.0 -->

- Flag subscriptions without unsubscribe (memory leaks) — prefer async pipe or takeUntilDestroyed.
- Flag heavy logic in templates; move to the component or a pipe.
- Flag direct DOM manipulation; use Angular APIs (Renderer2, bindings).
- Flag `any` types on new code where a real type is knowable.
