# Issue #25 targeted campaign report

Human approval remains `NOT_APPROVED`. Publishing remains `DISABLED`.

## Monday

`ALREADY_PUBLISHED — OUT_OF_SCOPE`

The existing Monday trace is preserved only as historical campaign evidence. Its
earlier `BLOCKED` result is not a verdict on the human-selected post already
published on LinkedIn. Monday was not evaluated, regenerated, edited, scored, or
given a new artifact during the targeted reruns.

## Tuesday

Existing definitive result: `READY_FOR_HUMAN_REVIEW`.

- Post score: `24/25`
- Hook: `4/5`
- First-comment score: `24/25`
- Deterministic gates: authority `PASS`; proof `NOT_REQUIRED`; honesty `PASS`;
  citation `PASS`; relevance `PASS`
- Integrated anti-slop: `PASS`
- Separate no-ai-slop: `PASS`
- Artifact: `NONE` (text-only policy)
- Visual QA: `NOT_REQUIRED`
- Trace: [tuesday/trace.json](tuesday/trace.json)
- Final post: [tuesday/post.md](tuesday/post.md)
- First comment: [tuesday/first-comment.md](tuesday/first-comment.md)

Tuesday was not rerun or modified.

## Wednesday

Definitive-trace forensic root cause: `K. RUNTIME_OR_CONTRACT_BUG`.

The original Narrative Editor contract encouraged authorial standing and did not
carry forward the Writer's prohibition on author-name, ownership, or edits to
source-anchored factual clauses. High-scoring candidates were therefore changed
into valid honesty/citation gate failures.

Targeted rerun result: `BLOCKED` after four new candidate cycles.

- Best pre-artisanal candidate: `25/25`, hook `5/5`, all deterministic gates pass
- Post-artisanal re-Critic: `22/25`, hook `4/5`
- Post-artisanal deterministic gates: all pass
- Final targeted blocker: `I. ARTISANAL_EDIT_REGRESSION`
- First comment: not run because the post fell below `24/25`
- Artifact/Visual QA: not run because the post fell below `24/25`
- Trace: [wednesday/trace.json](wednesday/trace.json)

## Thursday

Definitive-trace forensic root cause: `I. ARTISANAL_EDIT_REGRESSION`.

The original separate no-ai-slop edit rewrote source-anchored benchmark clauses.
Candidates that were `25/25` and gate-clean before the edit failed honesty and
citation after it. The fixed contract preserved every anchored clause in the
targeted rerun.

Targeted rerun result: `BLOCKED` after four new candidate cycles.

- Best pre-artisanal candidate: `25/25`, hook `5/5`, all deterministic gates pass
- Post-artisanal re-Critic: `23/25`, hook `4/5`
- Post-artisanal deterministic gates: all pass
- Final targeted blocker: `I. ARTISANAL_EDIT_REGRESSION`
- First comment: not run because the post fell below `24/25`
- Required artifact/Visual QA: not run because the post fell below `24/25`
- Trace: [thursday/trace.json](thursday/trace.json)

## Friday

Definitive-trace forensic root cause: `K. RUNTIME_OR_CONTRACT_BUG`.

The original Narrative Editor contract introduced author-name/ownership language
and rewrote factual mechanisms after Writer. The deterministic honesty and
citation gates correctly rejected those edits.

Targeted rerun result: `BLOCKED` after four new candidate cycles.

- Best candidate reaching the separate editor: `24/25`, hook `5/5`, all
  deterministic gates pass
- Post-artisanal raw Critic score: `20/25`
- Hook: `3/5`; hook cap applied; effective score `18/25`
- Post-artisanal deterministic gates: all pass
- Final targeted blocker: `I. ARTISANAL_EDIT_REGRESSION`
- First comment: not run because the post fell below the hook and score bars
- Artifact/Visual QA: not run because the post fell below the hook and score bars
- Trace: [friday/trace.json](friday/trace.json)

## Model assignments

Every targeted LLM invocation used the authenticated Codex runtime:

- Writer: `gpt-5.6-sol`, reasoning `high`
- Narrative Editor: `gpt-5.6-sol`, reasoning `max`
- Critic and post-edit re-Critic: `gpt-5.6-sol`, reasoning `ultra`
- Separate no-ai-slop editor: `gpt-5.6-sol`, reasoning `max`
- First Comment Writer: `gpt-5.6-sol`, reasoning `high`
- First Comment no-ai-slop editor: `gpt-5.6-sol`, reasoning `max`
- First Comment Reviewer: `gpt-5.6-sol`, reasoning `ultra`
- Artifact Editor: `gpt-5.6-sol`, reasoning `max`
- Visual QA: `gpt-5.6-sol`, reasoning `ultra`

Stages after a failed gate were not invoked. No LinkedIn write action was taken.
