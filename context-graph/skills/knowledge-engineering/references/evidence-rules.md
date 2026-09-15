# Evidence and Agreement Rules

Agreement does not mean that words overlap. The question scope and evidence meaning must match, and the answer must not exceed the evidence scope.

1. The question's subject, relationship, conditions, and reference date must match the Claim's `subject`, `predicate`, `scope`, and `as_of`.
2. Claim and Evidence must directly support or refute the same meaning. Search scores are not evidence.
3. The Evidence `source_id`, source revision, and content hash must match the verified original.
4. Another person must be able to find the same content with the locator. Otherwise the state is `unlocatable`.
5. A Claim must belong to an approved revision linked to a Review and Decision.
6. Every key sentence in an answer must trace to at least one Evidence record.
7. If evidence within the same scope is incompatible, return `conflict` instead of averaging it.
8. Do not turn unverified body content, stale, unknown, or unconfirmed rights/location into a definitive answer; return `abstain`.

Answer records must retain the question key, scope, as-of date, Claim ID, Evidence ID, Source revision, locator, and snapshot hash.
