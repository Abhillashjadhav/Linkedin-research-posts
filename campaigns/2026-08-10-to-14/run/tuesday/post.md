The exhaustion record may be more useful for an agent budget than the configuration field.

Design that record before polishing the happy path. It should answer what stopped, what remains unfinished, what state survives, whether the boundary was exact, and which actor can decide the next step. If the record cannot support that decision, the recovery experience will depend on guesswork.

Google's Antigravity documentation says max_total_tokens limits total input, output, and thinking tokens, excludes cached tokens, stops with status incomplete, and preserves work for continuation. The limit is best-effort, so usage may slightly exceed it depending on when checks occur between steps.

Product teams need to handle two distinct failure modes.

The first is semantic: treating incomplete work as failure, or presenting it as success because some output exists. Either choice hides the actual execution state from the user.

The second is operational: treating the budget as a perfectly precise boundary when enforcement may not land at the exact token. A responsible interface should preserve the distinction between a configured limit and observed usage without implying false precision.

A practical exhaustion artefact can become the contract between runtime, product and operator. It records the stopped state, exposes the remaining decision and makes continuation an explicit act of authority.

Cost control sets the boundary, while product judgement determines whether unfinished work remains understandable and recoverable when the budget runs out.
