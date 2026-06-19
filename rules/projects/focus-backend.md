<!-- version: 1.0 | project: Focus API (.NET) -->

- All DB access goes through the repository layer — flag direct DbContext use in controllers.
- All SQL must be parameterized. Flag any string-concatenated query (SQL injection).
- Public endpoints must check authorization. Flag any [HttpGet]/[HttpPost] missing an auth attribute.
- Watch for N+1 queries in EF Core loops. Suggest .Include() or projection.
- New service methods need a corresponding unit test. Flag if missing.
- Redis cache keys must use the shared key-builder, not raw string keys.
