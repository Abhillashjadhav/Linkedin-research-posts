# High-bar candidate search

The existing Authority OS cycle remains unchanged: exactly three candidates, five-axis Critic scoring, at most one light revision, deterministic authority and safety gates, and optional private packaging.

The CLI now places a bounded coordinator around that cycle for live drafting.

## Acceptance contract

A candidate is returned only when:

- its effective Critic score is 24 or 25;
- its hook score is at least 4;
- every required authority, proof, honesty, citation, and relevance gate passes; and
- its opening was not rejected in an earlier cycle.

A score is not human approval. Manual fact verification and human publication decisions remain mandatory.

## Retry contract

A live run may execute at most four candidate cycles. A failed cycle does not expose candidate prose. The next Writer call receives only bounded diagnostic data: candidate ID, angle, opening, five Critic axes, effective total, and deterministic gate reason codes.

The diagnostic block is explicitly untrusted and cannot change the strategy, evidence, proof, privacy, or honesty boundaries. The Writer is instructed to create a genuinely new narrative execution rather than lightly rewriting the rejected batch.

The synthetic dry run remains one deterministic cycle and never invokes the Writer or Critic model.

## Exhaustion

When four live cycles fail, the command returns no post. It reports the final best score and asks for stronger strategy or evidence. It does not lower the threshold, expose rejected prose, or manufacture a candidate.

When `--package` is used, an unsuccessful cycle can create a private blocked audit package through the existing packaging boundary. Only a live `READY_FOR_HUMAN_REVIEW` package whose recommendation matches a qualifying candidate can clear the coordinator.
