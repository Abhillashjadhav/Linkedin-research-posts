# LinkedIn Authority OS v6

Fluent content can still be generic, unsupported, strategically empty, or disconnected from the author's actual work.

Most AI-assisted content workflows optimise for producing more posts. This repository optimises for evidence-backed authority: demonstrated expertise that a reader can trace to research, product judgement, and approved proof—not vanity metrics. Research must support the claim, each draft must serve an explicit strategic outcome, voice guidance must stay grounded, deterministic gates must block unsupported content, and publication remains a human decision.

The system does not promise reach or strategic quality. It makes the inputs, checks, limitations, and human decisions inspectable.

## The architecture

```text
research → analysis → strategic routing → voice-grounded drafting
         → independent critique → deterministic gates → human review
         → measured learning
```

1. **Research** stores source bodies and provenance in a private, deduplicated ledger.
2. **Analysis** separates metadata clustering from full-body interpretation so a headline cannot become evidence.
3. **Strategic routing** carries an explicit reader, problem, hypothesis, product decision, authority statement, and goal into the brief.
4. **Voice-grounded drafting** produces three traceable candidates. Reconstructed voice assets shape style; they cannot support factual or personal claims.
5. **Independent critique** scores expression on a fixed five-axis rubric. The Critic cannot approve a draft or apply safety policy.
6. **Deterministic gates** check authority conversion, proof when required, honesty, citation, and relevance after the final model-written candidate exists.
7. **Human review** receives a private six-file package. A recommendation means review order only; fact verification, proof approval, selection, editing, and publication stay manual.
8. **Measured learning** compares mature, package-linked observations within the same strategic goal. It records evidence for review without claiming causation or changing the rubric automatically.

## Decisions the system cannot make

These are product and editorial judgements, not fields to infer from research or delegate to a model.

| Human decision | Why it stays human | Where it enters |
| --- | --- | --- |
| Target reader | Relevance depends on the author's intended relationship with a real audience. | `target_reader` in the private strategy input |
| Reader problem | Source popularity does not establish which decision a reader needs to make. | `reader_problem` |
| Hypothesis | A defensible mechanism requires product judgement, not topic summarisation. | `core_hypothesis` |
| Product decision | The practical action and trade-off must be chosen explicitly. | `product_decision` |
| Authority statement | The author decides which demonstrated expertise the work should establish. | `authority_statement` |
| Proof approval | The runtime can validate a manifest and trace a claim; only a person can approve the artefact and its public-safe wording. | Private proof manifest plus manual review |
| Final publication | Scores and gates establish review eligibility, not truth, taste, timing, or permission to publish. | Outside this repository |

[Human judgment in the complete workflow](docs/HUMAN_JUDGMENT.md) documents the remaining manual boundaries, including source selection, personal voice approval, fact verification, candidate choice, performance entry, and interpretation of learning reports.

## 60-second synthetic walkthrough

Run one offline command from the repository root:

```sh
./bin/linkedin-os draft --dry-run --package
```

The visibly synthetic fixture exercises the complete decision path without calling Writer or Critic models:

- a two-pass analysis selects a fixture topic;
- explicit synthetic strategy fields route it to a goal while leaving format separate;
- exactly three prevalidated candidates receive deterministic fixture scorecards;
- all five local gates run on every final candidate; and
- one private, review-only package is written under `outputs/`.

The command prints the package ID and path. The package remains `FIXTURE_REVIEW_ONLY`, has no recommended candidate, requires manual fact verification, records no approval, and cannot publish.

One generated package has this structure:

```text
outputs/YYYY-MM-DD/<topic-slug>[-N]/
├── brief.md
├── candidates.md
├── evaluation.json
├── sources.md
├── final-package.md
└── manifest.json
```

| File | Why it exists |
| --- | --- |
| `brief.md` | Shows the reader, problem, hypothesis, decision, authority statement, route, and known evidence limitations that constrained drafting. |
| `candidates.md` | Keeps all three final candidates and their claim IDs visible so human choice is not collapsed into a score leader. |
| `evaluation.json` | Preserves Critic scores, deterministic ranking, revision history, gate results, and computed eligibility for audit. |
| `sources.md` | Provides query-free public source metadata and optional public-safe proof without exposing research bodies or local proof paths. |
| `final-package.md` | Turns machine output into a human checklist: verify facts and proof, inspect voice, choose or reject a candidate, and decide whether to publish. |
| `manifest.json` | Records provenance, exact inventory, safety statuses, and package completeness. It is written last as the package commit marker. |

## Run the complete local check

The runtime requires Python 3.11 or newer, macOS or Linux, and no third-party packages.

```sh
make setup
make doctor
./bin/linkedin-os research --dry-run
./bin/linkedin-os draft --dry-run
./bin/linkedin-os draft --dry-run --package
make check
```

`init`/`make setup` is the explicit state-creating operation. `doctor` is read-only. The dry-run research command stores only visibly synthetic evidence with preserved provenance; live drafting will not consume it. `make check` runs the privacy gate before the warnings-as-errors test suite.

## What each boundary prevents

### Research is evidence; proof is attestation

Research supports external factual claims. A proof manifest attests to a local artefact, ownership sentence, or public-safe result. Opportunity work requires proof, while Reach and Authority may include it when an exact personal or ownership statement is necessary. A proof ID is additive: it cannot replace research evidence.

Live research enters only through an explicit private JSON or JSONL import. The ledger records `private-import`, `synthetic-fixture`, or quarantined `legacy-unverified` provenance, canonicalises public URLs, and deduplicates canonical URL and normalised body hash independently. Analysis reports recency, readable-body, source-quality, and staleness limitations instead of filling gaps.

### Goal is an outcome; format is a container

The three goals are Reach, Authority, and Opportunity. They describe the outcome to evaluate, not the medium to produce. Output format is an independent optional choice among text, carousel, vertical video, article, and artefact demo. Omitting `--format` leaves it unselected.

The default four-slot mix routes to Reach, Authority, Authority, and Opportunity. A fifth slot requires both an explicit goal and a confirmed strong current incident or launch; the runtime does not infer either judgement.

### Writer and Critic have narrow roles

For live drafting, the Writer receives only the selected brief, selected evidence, reconstructed voice guidance, and an optional public-safe proof projection. It returns exactly three unscored plain-text candidates with `id`, `angle`, `text`, and `claim_ids`. Source queries, local proof paths, and artefact contents do not enter the model prompt.

The Critic scores `hook_strength`, `middle_escalation`, `earned_closer`, `specificity_and_source_quality`, and `voice_fidelity` from 1 to 5. Python validates the scorecard, calculates totals, applies the hook cap, and establishes a deterministic score leader. A 22–23 result permits at most one light revision and one rescore. A 24–25 result advances to deterministic gates; it is not approval.

Live Writer and Critic calls require both an explicit private strategy file and `--allow-model-egress`. They run with zero tools and no persisted model session. Fixture drafting and scoring are offline.

### Deterministic gates follow model critique

Every final candidate is checked locally in this order:

1. `authority_conversion`
2. `proof`
3. `honesty`
4. `citation`
5. `relevance`

The gates return only `PASS`, `FAIL`, or `NOT_REQUIRED` with static reason codes. They conservatively check structural traceability, including clause polarity, ordered relationships, named and numeric markers, exact query-addressed support, proof IDs, audience relevance, and overlap with the stated product decision. They do not prove truth. `manual_fact_verification_required` is always true.

### Human review is the terminal content decision

A live candidate is eligible for review only when its final Critic band advances to gates and every required gate passes. The package recommends the first eligible candidate in deterministic Critic order, or writes a complete `BLOCKED` package when none qualify. The manifest always keeps:

```text
human_approval_status = NOT_APPROVED
publishing_status = DISABLED
manual_fact_verification_required = true
```

There is no publish, schedule, approve, message, comment, browser-automation, or LinkedIn write command.

### Learning waits for comparable evidence

Performance entry is manual and accepts only an eligible candidate from a committed live package after the operator confirms that publication already happened elsewhere. Paid and organic rows remain separate. The package is not mutated.

The canonical learning cohort uses one organic 72-hour observation per package when actual observation age is at least 72 and less than 96 hours. Earlier checkpoints are immature, later observations are reported separately, and comparisons stay within one goal. Critic alignment and possible rubric-calibration review require repeated cross-package evidence; even a repeated reversal creates a human review suggestion, never an automatic edit.

## Safety summary

- Private research, proof manifests, performance imports, databases, review packages, and learning reports remain under ignored local paths.
- Model egress is explicit, bounded, query-stripped, tool-free, and stateless.
- Fixture provenance cannot become a live recommendation.
- Package, database, import, and report operations fail closed on unsafe path or schema conditions.
- The Git-aware privacy check scans tracked, prospective, and staged public content while avoiding ignored private data and never printing matched secret values.
- CI has read-only repository permission and no scheduled trigger.
- Publishing is intentionally absent.

The low-level POSIX permissions, descriptor-relative file handling, atomic write protocol, SQLite attestation, privacy-scanner behaviour, and platform limitations are documented in [Security and privacy reference](docs/SECURITY_AND_PRIVACY.md).

## Reference map

- [Workflow reference](docs/WORKFLOW.md) — implemented research, analysis, drafting, critique, gate, package, performance, and learning contracts.
- [Product decisions](docs/PRODUCT_DECISIONS.md) — why the major boundaries exist.
- [Human judgment](docs/HUMAN_JUDGMENT.md) — where author expertise and manual approval enter.
- [What the repository shows](docs/WHAT_I_LEARNED.md) — evidence-backed lessons with explicit manual-review blocks.
- [Security and privacy reference](docs/SECURITY_AND_PRIVACY.md) — fail-closed filesystem, egress, privacy, and CI details.
- [Architecture decision](ARCHITECTURE_DECISION.md) — current runtime boundary and exclusions.
- [Recovery manifest](RECOVERY_MANIFEST.md) — provenance of recovered and reconstructed assets.

The rationale follows the repository's atomic implementation history: evidence recovery and offline CLI (#2–#3), research and analysis (#4–#5), routing and drafting (#6–#7), Critic scoring and deterministic gates (#8–#9), human-review packages (#10), and package-linked performance plus mature weekly learning (#11–#12).
