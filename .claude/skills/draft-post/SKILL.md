---
name: draft-post
description: Prepare evidence-grounded LinkedIn drafts through bounded research, Critic scoring and a private human-review package. Use for /draft-post, today's LinkedIn draft, Thursday capability discovery, a requested post topic, or a review package. Apply the existing OS weekday routing without requiring repeated instructions. Never publish, schedule, comment, message, or record human approval.
---

# Draft Post

Use only `./bin/linkedin-os`. Do not bypass its validation or invoke the role prompts directly.

## Thursday inside the existing OS

Use [the Thursday capability workflow](../../../docs/THURSDAY_CAPABILITY_WORKFLOW.md)
when the caller routes `thursday-capability-v1`. Weekly slot 3 is Thursday; in a
five-day campaign, route by the actual Thursday day label, not its campaign index.
Discovery may infer Thursday from its Asia/Kolkata `as-of` date when no slot is
supplied. Carry the resolved mode into drafting, comments and artifact planning.
Do not ask the user to repeat the workflow or create a separate global skill.

Search for a useful, surprising capability with executable code, a visible real
demo, primary evidence and observed current attention. Include indie projects,
GitHub releases/trending, Show HN and Hugging Face. Discovery enforces a capability
window of at most seven days; an older repo needs an evidenced substantive update
inside that window. Preserve original and meaningful-release dates, and do a last-48-hour sweep within
the existing budget. Missing counts remain unknown; momentum is not factual proof.
This mode supersedes incident-first only for Thursday. Other weekdays, goals and
existing authorization remain unchanged.

Deliver the review package with post, first comment and its actual review status, demo/source
references, concise alternatives and honest artifact status. Keep the benefit in
the post and deeper mechanism in the comment/video. Use visible output and a
coherent diagram when useful; slide cards are not a working demonstration. A
VIDEO_PLAN or rendered SVG is not a finished MP4. Retain the grounded post if a
later visual stage is incomplete and report the limitation. Do not add a new
mandatory topic-approval round; publication remains manual.

For a five-day `--run-spec` campaign, the CLI owns the full executable order:
Scout → Thesis → Writer → Narrative Editor → Critic → deterministic gates →
integrated Anti-AI-Slop → bounded regeneration → separate no-ai-slop edit →
post-edit Re-Critic/gates → First Comment Writer/Reviewer → Artifact Editor →
rendered artifact → Visual QA → human review. Do not invoke any of those role
prompts directly.

## Choose the run mode

- For an offline workflow check, use `--dry-run`. Fixture output is synthetic, invokes no model, runs one deterministic cycle, never recommends a candidate, and must not be published.
- For a live draft, require an existing private research ledger, a user-supplied `--strategy-input` file, and the user's explicit `--allow-model-egress` consent. Do not infer consent or claim that this command collects live research.
- Keep strategic goal and output format independent. Pass only values the user selected. Opportunity additionally requires a user-supplied `--proof-manifest`; Reach and Authority may use one when exact public-safe proof or attestation is needed.
- Add `--package` when the user requests a local human-review package, including the established Thursday package workflow. Preserve warnings and review status; do not convert them into approval.

Examples:

```sh
./bin/linkedin-os draft --dry-run --goal authority
./bin/linkedin-os draft --dry-run --goal reach --format text --package
./bin/linkedin-os draft --strategy-input data/private/strategy.json --allow-model-egress
./bin/linkedin-os draft --goal opportunity --strategy-input data/private/strategy.json \
  --proof-manifest data/private/proof.json --allow-model-egress --package
./bin/linkedin-os draft --run-spec campaigns/2026-08-10-to-14/spec.json \
  --trace-output campaigns/2026-08-10-to-14/run \
  --no-ai-slop-skill /tmp/no-ai-slop/SKILL.md \
  --no-ai-slop-eval /tmp/no-ai-slop/eval.md
```

Use `--campaign-day <Weekday>` only after a complete run; it reruns that day
and rebuilds the aggregate from the five persisted traces. Never rerun a day
listed in the campaign spec's `preserve_days`.

If live prerequisites are missing, report the exact missing input. Do not replace missing research, strategy, proof, ownership, or model-egress consent with invented material or a silent fixture run.

## High-bar search

The CLI runs up to four live candidate cycles. Each cycle still owns exactly three candidates and at most one light revision. A candidate is returned only when all of these are true:

- effective Critic score is at least 17;
- hook and voice are at least 4;
- middle escalation, earned closer and specificity/source quality are at least 3.

Python owns acceptance. Retain factual/source validation and the active runtime's
advisory findings. Feed bounded diagnostics into the next permitted attempt
without changing strategy or inventing evidence. Stop immediately at all five
axis minima. On bounded exhaustion, return the best grounded draft with
`COMPLETED_WITH_WARNINGS`; missing valid evidence or malformed required output
still fails. Do not replace this contract with historical /50 rubrics.

## Return the result

Return the accepted candidate or safely retained best draft, together with its
actual scores, advisory findings and unmet targets. Never upgrade a score or gate
pass into human approval. Keep retained warnings visible.

When `--package` succeeds, return the printed package ID and local package path.
The current package has eight files (legacy packages may have six) and remains
private under ignored `outputs/`. Standalone Thursday `post.md` and
`source-comment.md` are companions; the comment uses validated capability metadata
and records editorial score `NOT_EVALUATED`. Do not call it Critic-approved.
`final-package.md` and `evaluation.json` carry the actionable source-linked video
plan and `INCOMPLETE` full-package status pending actual rendered, verified media.
The accepted video production reference is 1920 × 1080, 30 fps, approximately 78
seconds unless an explicit brief overrides it.

A `READY_FOR_HUMAN_REVIEW` status is review eligibility only:
`human_approval_status` remains `NOT_APPROVED`, `publishing_status` remains `DISABLED`,
and manual fact verification remains required. Fixture and blocked
packages are not eligible for performance recording.

Never publish, schedule, comment, message, automate a browser, mutate package approval state, or run performance/learning commands implicitly. Publication, if any, happens later through a separate human-controlled process.
