# Bounded conversation-momentum discovery

The zero-paid-API momentum layer is intentionally split into bounded live-web stages so one model call is not responsible for discovering and fully researching all ten topics.

```text
Shallow topic discovery: 10 topics
→ momentum enrichment in two-topic batches
→ timed-out batch splits to one-topic research automatically
→ local validation + deterministic Python scoring
→ ranked top 5
→ separate authority-fit scoring
→ body-verified source research
→ thesis generation
```

The first call returns only `id`, `topic`, and `why_now`. It does not calculate momentum scores.

Each enrichment call collects the observable basis values required by the existing momentum rubric: conversation breadth, visible engagement, acceleration, cross-platform confirmation, and freshness. Missing evidence remains `UNKNOWN`/`null`.

The normal enrichment size is two topics. If a multi-topic live-web call times out, the adapter splits that batch and retries each half. A one-topic timeout fails explicitly rather than looping forever. Non-timeout schema, evidence, or model errors are never retried as smaller batches.

The enrichment batches must preserve the exact topic IDs and topic text discovered in the first pass. Duplicate IDs, missing IDs, renamed topics, or the wrong number of batch candidates fail closed. After all ten topics return, the existing local validator rechecks the complete set before any ranking occurs.

The CLI prints concise progress before topic discovery and before/after each enrichment call so a long live-web request is visible rather than appearing hung.

The scoring boundary is unchanged: the model reports observable evidence and numeric basis values; Python derives the 0–5 scores and ranking. Authority fit remains separate and cannot reorder conversation momentum.

This remains a public-web proxy. It does not use paid APIs, authenticated X/LinkedIn sessions, private data, browser sessions, or publishing actions, and it does not claim an exact X/Twitter popularity ranking.
