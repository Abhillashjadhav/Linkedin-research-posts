# V0 vs V1 controlled quality comparison

Use this only for local product evaluation. It does not publish, schedule, record performance, or mutate the frozen V0 branch.

## What it compares

The runner resolves two exact Git commits before starting:

- V0: `baseline/v0-pre-eval-v1`
- V1: current `main`

It then creates two temporary detached Git worktrees and gives both versions the exact same:

- research JSON/JSONL import;
- strategy JSON;
- topic;
- goal and optional output format;
- proof manifest when the goal is `opportunity`.

Each version gets its own private SQLite database and output tree. Temporary worktrees are removed after the run.

The resulting comparison is stored only under ignored local state:

```text
data/private/v0-v1-comparisons/<UTC-run-id>/
├── comparison.md
├── comparison.json
├── v0/
│   ├── init.log
│   ├── research.log
│   ├── draft.log
│   └── package/
└── v1/
    ├── init.log
    ├── research.log
    ├── draft.log
    ├── package/
    └── v1-evals/          # when V1 produced eval sidecars
```

Nothing under this directory is tracked by Git.

## Prerequisites

Run from a current local clone of `Linkedin-research-posts` with both model CLIs used by the live repository authenticated:

```bash
which claude
which codex
```

The runner intentionally fails before model egress if either executable is unavailable.

## Strategy input

The strategy file is one private JSON object with the existing five-field contract:

```json
{
  "target_reader": "People across the GenAI ecosystem, from early learners to practitioners",
  "reader_problem": "Teams struggle to keep up with fast-moving GenAI changes and identify what matters",
  "core_hypothesis": "A concrete practitioner interpretation can make one current GenAI change immediately useful",
  "product_decision": "Explain one atomic value and what a reader should do differently",
  "authority_statement": "Demonstrate practical GenAI product judgment through a plausible, evidence-bounded solution"
}
```

Keep this file under `data/private/` on your machine.

## Research input

Use the same real body-read research JSON/JSONL you want both versions to receive. Each item must satisfy the existing research contract, for example:

```json
[
  {
    "url": "https://example.com/source",
    "title": "Source title",
    "body": "Body-read source text used as evidence.",
    "source": "Example",
    "author": "Author",
    "published_at": "2026-08-28T00:00:00Z",
    "source_quality": "primary"
  }
]
```

Do not create different research pools for V0 and V1; that would confound the experiment.

## Run one authority comparison

```bash
./bin/compare-v0-v1 \
  --research data/private/compare/research.json \
  --strategy data/private/compare/strategy.json \
  --topic "agent reliability" \
  --goal authority \
  --format text
```

The command prints only the local path to `comparison.md` when it succeeds.

## What to inspect

Open the generated `comparison.md`, then compare:

1. `v0/package/candidates.md` vs `v1/package/candidates.md`;
2. the opening/hook;
3. whether there is exactly one useful atomic value;
4. mechanism / trade-off / decision depth;
5. voice and AI-slop patterns;
6. factual inspectability;
7. Critic scoring and gate behavior in each `draft.log`;
8. V1 contract evidence in `v1/v1-evals/` when present.

The runner deliberately sets `winner: null`. The first comparison is product evidence, not statistical proof. Repeat on multiple topics before deciding that V1 is categorically better or worse.
