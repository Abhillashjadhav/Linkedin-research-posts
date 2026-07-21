# What the repository shows

The filename supports a future portfolio narrative, but the text below is an evidence-backed reading of the repository—not a first-person account and not a claim about the owner's private experience. Each section must be manually reviewed before it is converted into personal language.

## Traceability and proof solve different trust problems

The ledger and citation gates show whether a factual statement points to body-read research. Proof manifests show whether a bounded public claim or personal attestation points to a local artefact. Keeping the identifiers additive prevents one kind of trust from impersonating the other.

Evidence: PRs #4 and #9, `research_items` provenance, proof-manifest validation, and the gate test suite.

> **HUMAN REVIEW REQUIRED**
>
> Confirm that this distinction reflects the owner's actual product reasoning. Add a personal example only when the underlying work and disclosure are approved.

## Strategy becomes inspectable when the decision is explicit

Topic selection alone does not establish usefulness. The strategy brief makes the intended reader, unresolved problem, mechanism, product decision, and authority statement reviewable before drafting. The gate then checks conversion against the supplied decision rather than rewarding topical fluency.

Evidence: PR #6, strategy routing, brief rendering, and the `authority_conversion` and `relevance` gates.

> **HUMAN REVIEW REQUIRED**
>
> Validate the five strategy fields against real author expertise. Do not describe the routing as strategically successful without outcome evidence.

## Model judgement is useful when its authority is narrow

The Critic provides a repeatable lens on expression, and the one-revision limit bounds iteration. Its score is deliberately prevented from approving, proving, or publishing. Deterministic policy checks and human editorial judgement remain separate.

Evidence: PRs #8–#10, the score-only Critic schema, gate ordering, and package safety statuses.

> **HUMAN REVIEW REQUIRED**
>
> Confirm that the five Critic axes match the owner's editorial standards. A high score should not be cited as evidence of factual or strategic quality.

## A review package is an interface for judgement

The six-file package keeps brief, candidates, evaluation, sources, checklist, and provenance separate. That structure lets a reviewer question the model's ordering, inspect limitations, and reject every candidate without losing the audit trail.

Evidence: PR #10, package schema, manifest-last commit protocol, and package tests.

> **HUMAN REVIEW REQUIRED**
>
> Review at least one real package end to end before claiming that the structure improves decision quality. Record any files or fields the reviewer did not use.

## Performance needs comparable exposure before it can inform changes

Package-linked metrics avoid free-form attribution, and the mature organic cohort avoids combining observations with different exposure or distribution channels. Repeated evidence thresholds keep a single result from rewriting the rubric.

Evidence: PRs #11–#12, performance checkpoint validation, 72–96-hour cohort filtering, within-goal outcome vectors, and calibration thresholds.

> **HUMAN REVIEW REQUIRED**
>
> Confirm that the checkpoint windows and outcome vectors fit the owner's actual operating context. Treat observed associations as descriptive until a stronger evaluation design exists.

## Safety is partly defined by absent capabilities

The CLI can import, analyse, draft, score, gate, package, record, and review. It cannot browse authenticated sessions, mutate approval, schedule, message, or publish. Privacy tests and CI protect that absence as a product boundary.

Evidence: the exact CLI-surface test, privacy scanner, read-only CI permissions, and publishing-disabled package state.

> **HUMAN REVIEW REQUIRED**
>
> Confirm that no external workflow bypasses this boundary before describing publication as fully human-controlled.

## Voice assets need ownership, not just reconstruction

The available voice guide and performance anchors are explicitly reconstructed. They provide useful constraints, but only the author can decide whether the result sounds personal and whether any historical performance statement is accurate enough to disclose.

Evidence: the recovery manifest and both files under `data/voice/`.

> **HUMAN REVIEW REQUIRED**
>
> Approve, edit, or reject each personal voice section and performance anchor before public reuse. Never present reconstructed wording as an original post or quotation.
