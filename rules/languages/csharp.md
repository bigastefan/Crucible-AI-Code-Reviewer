<!-- version: 1.0 -->

- Flag `async void` (except event handlers); use `async Task`.
- Flag missing `ConfigureAwait`/blocking `.Result`/`.Wait()` on async paths (deadlock risk).
- Flag `IDisposable` resources not wrapped in `using`.
- Flag swallowed exceptions (empty `catch`) and catching bare `Exception` without rethrow/log.
- Flag mutable `public` fields where a property is intended.
