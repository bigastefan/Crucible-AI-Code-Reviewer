<!-- version: 1.0 -->

- Flag `any` on new code where a real type is knowable; prefer `unknown` + narrowing.
- Flag non-null assertions (`!`) used to silence the compiler over real null handling.
- Flag floating promises (un-awaited async calls) that drop errors.
- Flag `==`/`!=` where `===`/`!==` is intended.
- Flag use of `var`; prefer `const`/`let`.
