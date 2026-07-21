# Product decisions

This record explains the boundaries that define LinkedIn Authority OS v6. The decisions are product constraints, not implementation accidents. They preserve evidence-backed authority—demonstrated expertise that can be traced to research, product judgement, and approved proof—while leaving consequential editorial decisions with a person.

## Research and proof are distinct

**Decision:** Keep research evidence IDs and proof IDs separate. Proof may be added to a candidate, but it cannot replace research support.

Research and proof answer different questions:

- Research asks, “What external evidence supports this factual claim?”
- Proof asks, “What approved artefact or attestation supports this ownership, experience, or result claim?”

Combining them would allow an artefact to stand in for independent evidence, or an external source to imply that the author performed work that was never attested. Opportunity routes therefore require a validated proof manifest, while every candidate still needs body-read research evidence. Reach and Authority may use proof only when an exact public-safe artefact or personal statement is relevant.

The runtime validates the local proof artefact without reading its contents. Only the proof ID, type, public claim, and exact approved attestations may cross the model boundary. Human approval is still required because structural validation cannot decide whether the artefact or wording is appropriate to disclose.

Evidence: [workflow implementation](../src/authority_os/workflow.py), [gate tests](../tests/test_gates.py), and the atomic research/proof changes in PRs #4 and #9.

## Goal and format are separate

**Decision:** Represent the intended outcome and the output container as independent fields.

Reach, Authority, and Opportunity answer why the work exists and which outcomes may later be compared. Text, carousel, vertical video, article, and artefact demo answer how the work may eventually be presented. Inferring format from goal would hide a product decision, constrain experimentation, and contaminate learning by treating a medium as an outcome.

The router therefore accepts any valid goal/format pair, leaves format unselected when omitted, and carries both fields separately into the package and performance snapshot. “Authority” means demonstrated expertise; it does not mean follower count or engagement volume.

Evidence: [strategy tests](../tests/test_strategy.py), [workflow reference](WORKFLOW.md), and PR #6.

## Critic scoring cannot approve

**Decision:** Limit the Critic to a five-axis score-only response and calculate all totals, bands, and ranking in deterministic Python.

The Critic evaluates expression: hook strength, middle escalation, earned closer, specificity and source quality, and voice fidelity. Those are useful but fallible model judgements. A strong score does not establish factual support, author permission, proof suitability, voice authenticity, or publication readiness.

The score leader is therefore only an ordering signal. A 24–25 score advances to local gates. A 22–23 score permits one bounded revision. No score can set approval state, recommend publication, schedule content, or publish.

Evidence: [Critic boundary](../.claude/agents/critic.md), [Critic tests](../tests/test_critic.py), and PR #8.

## Deterministic gates follow model critique

**Decision:** Apply the fixed local gates to the final model-written candidate after Critic scoring and any single allowed revision.

Model critique and policy checks serve different purposes. The Critic ranks communication quality; deterministic gates enforce inspectable minimum conditions for authority conversion, proof, honesty, citation, and relevance. Mixing these jobs inside one model prompt would make failures difficult to reproduce and would allow a model score to blur into safety policy.

The order also matters. A revision can introduce or remove claims, so the exact final text must be gated. Package generation revalidates the scores and recomputes the gates before writing eligibility. The gates use conservative structural heuristics and static reason codes. They can block unsupported content, but they cannot prove truth; manual fact verification remains mandatory.

Evidence: [gate implementation](../src/authority_os/workflow.py), [package implementation](../src/authority_os/package.py), [gate tests](../tests/test_gates.py), and PRs #9–#10.

## Publishing is disabled

**Decision:** Provide no command, client, credential path, scheduler, or browser automation that can publish or mutate approval state.

Publication is an external, identity-bearing action. Research provenance, model scores, deterministic gates, and package eligibility do not establish the author's final factual confidence, taste, timing, consent, or platform context. Keeping publication outside the runtime makes the human boundary enforceable rather than advisory.

Performance recording starts only after a person confirms that an eligible candidate was independently published elsewhere. It records that assertion without modifying the immutable review package. The CLI surface and privacy tests reject publishing-adjacent expansion.

Evidence: [production-boundary tests](../tests/test_hardening.py), [privacy implementation](../src/authority_os/privacy.py), and PRs #10–#12.

## Performance learning waits for mature checkpoints

**Decision:** Use one organic observation with an actual age of 72–96 hours as the canonical comparison cohort, keep goals and channels separate, and require repeated evidence before suggesting rubric review.

Early metrics are incomplete, paid distribution is not comparable with organic distribution, and observations with materially different exposure time should not be ranked as though they were equal. The 72–96-hour window makes the comparison rule explicit. It is a cohort definition, not a claim that every post has reached a final outcome.

Outcome vectors differ by goal because the intended result differs. Comparisons remain descriptive and within goal. Critic-versus-outcome alignment needs at least three distinct posts and three scorable cross-package pairs. Axis-calibration review needs at least three posts on each side of a score split, two shared publication weeks, and a repeated reversal. Even then, the system emits only `REVIEW_AXIS_CALIBRATION`; it never edits the rubric.

Evidence: [learning implementation](../src/authority_os/learning.py), [learning tests](../tests/test_learning.py), and PRs #11–#12.

## Decision status

These boundaries are active in the CLI, deterministic checks, package schema, privacy scan, and test suite. Any future change that combines evidence with proof, goal with format, scoring with approval, or learning with automatic rubric mutation changes the product—not merely the code—and requires explicit human review.
