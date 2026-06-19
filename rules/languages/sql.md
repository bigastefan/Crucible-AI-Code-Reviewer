<!-- version: 1.0 -->

- Flag any query built by string concatenation of inputs — require parameterization (SQL injection).
- Flag `SELECT *` in production queries; list the columns needed.
- Flag missing `WHERE` on `UPDATE`/`DELETE` (mass-mutation risk).
- Flag queries on large tables with no indexable predicate.
- Flag schema changes (DROP/ALTER) without a corresponding migration note.
