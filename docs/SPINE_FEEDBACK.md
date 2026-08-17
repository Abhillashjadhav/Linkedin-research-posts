# Narrative spine routing and feedback

The daily discovery path keeps its existing evidence and human-selection boundaries, but `./bin/linkedin-os discover` now adds two advisory fields to each Thesis option:

- `recommended_spine` — one of `counterposition`, `failure_reversal`, `research_discovery`, `operator_tradeoff`, or `unresolved_tension`;
- `spine_fit_reason` — why the current evidence and conversation surface naturally fit that shape.

The recommendation is not a Writer template, weekday rule, approval, or publishing instruction. The five-field downstream strategy contract is unchanged. A human still chooses the thesis and the normal Writer/Critic/anti-slop/human-review pipeline remains authoritative.

## Private performance snapshots

After a post is manually published outside this runtime, an observed snapshot can be recorded locally:

```sh
./bin/linkedin-os record-spine-performance \
  --post-url 'https://www.linkedin.com/posts/...' \
  --published-at '2026-08-17T09:00:00+05:30' \
  --topic 'agent reliability' \
  --attention-source x_and_web \
  --spine counterposition \
  --impressions 1200 \
  --engagements 15 \
  --observed-at '2026-08-20T09:00:00+05:30'
```

Optional metrics are `qualified-comments`, `reposts`, `saves`, `profile-visits`, and `relevant-followers`. Use `--breakout-outlier` only for a post deliberately excluded from baseline strategy comparison while preserving it as a breakout case study.

Records are appended to ignored owner-only `data/private/spine-performance.jsonl`. The command does not call LinkedIn, publish, or modify strategy.

## Median review

```sh
./bin/linkedin-os spine-review
```

The review uses only the latest snapshot for each post URL and reports, by spine:

- observation count;
- median impressions;
- median engagements;
- median engagement rate.

Breakout outliers are excluded by default and listed separately. `--include-outliers` is available for deliberate breakout inspection. A spine is labelled `READY_TO_COMPARE` only after at least five baseline observations; smaller samples remain `INSUFFICIENT_SAMPLE`.

The report is observational only. It never changes prompts, thresholds, routing, or publication state automatically.
