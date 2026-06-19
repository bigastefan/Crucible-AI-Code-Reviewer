<!-- version: 1.0 -->

- Flag bare `except:` or `except Exception` that swallows errors without logging/re-raising.
- Flag mutable default arguments (`def f(x=[])`).
- Flag use of `subprocess` with `shell=True` on any non-constant input (injection).
- Flag broad `# type: ignore` / missing types on new public functions where a type is knowable.
- Flag resources opened without a context manager (`with`).
- Flag `assert` used for runtime validation in production paths (stripped under `-O`).
