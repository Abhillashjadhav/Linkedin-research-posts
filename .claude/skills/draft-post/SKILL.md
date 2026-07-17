---
name: draft-post
description: Prepare three evidence-grounded LinkedIn draft candidates, Critic scores, safety gates, and an optional local human-review package through the fixed Authority OS CLI. Use for /draft-post, today's LinkedIn draft, a requested post topic, or a request for a review package. Never publish, schedule, comment, message, or record human approval.
---

# Draft Post

Use only `./bin/linkedin-os`. Do not bypass its validation or invoke the role prompts directly.

## Choose the run mode

- For an offline workflow check, use `--dry-run`. Fixture output is synthetic, invokes no model, never recommends a candidate, and must not be published.
- For a live draft, require an existing private research ledger, a user-supplied `--strategy-input` file, and the user's explicit `--allow-model-egress` consent. Do not infer consent or claim that this command collects live research.
- Keep strategic goal and output format independent. Pass only values the user selected. Opportunity additionally requires a user-supplied `--proof-manifest`; Reach and Authority may use one when exact public-safe proof or attestation is needed.
- Add `--package` only when the user requests a local human-review package. Drafting without it prints the validated candidates, Critic scores, and gate results without writing a package.

Examples:

```sh
./bin/linkedin-os draft --dry-run --goal authority
./bin/linkedin-os draft --dry-run --goal reach --format text --package
./bin/linkedin-os draft --strategy-input data/private/strategy.json --allow-model-egress
./bin/linkedin-os draft --goal opportunity --strategy-input data/private/strategy.json \
  --proof-manifest data/private/proof.json --allow-model-egress --package
```

If live prerequisites are missing, report the exact missing input. Do not replace missing research, strategy, proof, ownership, or model-egress consent with invented material or a silent fixture run.

## Return the result

The CLI owns selected-cluster analysis, strategic routing, exactly three voice-grounded candidates, five-axis Critic scoring, at most one revision, and the five deterministic local gates. Report its candidate and gate outcome without upgrading a score or gate pass into approval.

When `--package` succeeds, return the printed package ID and local package path. The package has six committed files and remains private under ignored `outputs/`. A `READY_FOR_HUMAN_REVIEW` status is review eligibility only: `human_approval_status` remains `NOT_APPROVED`, `publishing_status` remains `DISABLED`, and manual fact verification remains required. Fixture and blocked packages are not eligible for performance recording.

Never publish, schedule, comment, message, automate a browser, mutate package approval state, or run performance/learning commands implicitly. Publication, if any, happens later through a separate human-controlled process.
