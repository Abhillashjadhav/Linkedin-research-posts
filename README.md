# LinkedIn Authority OS v6

A small, evidence-backed research and drafting workflow for Abhillash Jadhav. It turns a topic or current GenAI product signal into three drafts, applies a frozen 25-point critic and binary safety gates, allows at most one revision, and produces a five-file package for human approval.

It cannot publish to LinkedIn. There is no publish, comment, message, browser, OAuth, or schedule command.

## Five-minute quick start

Requires Python 3.11 or newer. Setup installs nothing from the network.

```sh
git switch build/linkedin-authority-os-v6-complete
make setup
make doctor
make test
./bin/linkedin-os research --dry-run
./bin/linkedin-os draft --dry-run --goal authority
```

The last command writes a synthetic workflow check to `outputs/YYYY-MM-DD/<slug>/`. Its `final-package.md` is visibly labelled fixture data and must not be published.

## Daily run

With an authenticated local Claude CLI:

```sh
./bin/linkedin-os draft --goal authority
```

For a supplied topic and verified Opportunity proof:

```sh
./bin/linkedin-os draft --topic "PM-agent-OS" --goal opportunity \
  --proof-type repository --proof-value "https://github.com/OWNER/REPOSITORY"
```

The optional Claude executable is the only live model surface. Scout receives read-only `WebSearch` and `WebFetch`; Analyst, Writer, and Critic receive no tools. Python alone writes the private database and approval package.

## Commands

```sh
make setup
make doctor
make test

./bin/linkedin-os init
./bin/linkedin-os doctor
./bin/linkedin-os research
./bin/linkedin-os research --input data/private/research.jsonl
./bin/linkedin-os draft
./bin/linkedin-os draft --goal reach
./bin/linkedin-os draft --goal authority
./bin/linkedin-os draft --goal opportunity
./bin/linkedin-os draft --topic "PM-agent-OS" --goal opportunity
./bin/linkedin-os record-performance --help
./bin/linkedin-os weekly-review
```

Claude Code usage is preserved through `/draft-post`, `/draft-post --goal authority`, and `/draft-post PM-agent-OS --goal opportunity`.

## Private research import

Keep private files under `data/private/`; the directory is ignored. JSON may be a list or `{"items": [...]}`. JSONL uses one object per line. Each source requires:

```json
{
  "canonical_url": "https://primary.example/source",
  "title": "Source title",
  "body": "Relevant source body",
  "source": "Publisher",
  "author": "Author",
  "published_at": "2026-07-16T09:00:00Z",
  "source_quality": "primary"
}
```

The CLI canonicalises URLs and deduplicates both canonical URL and normalised content hash in `data/private/authority_os.sqlite`. Missing private inputs do not break setup.

## Performance loop

Record paid and organic observations separately at `2h`, `24h`, `72h`, and optionally `7d`:

```sh
./bin/linkedin-os record-performance \
  --post agent-reliability-budgets --checkpoint 24h --channel organic \
  --impressions 1000 --profile-visits 30 --saves 12 --sends 5

./bin/linkedin-os record-performance --csv data/private/performance.csv
./bin/linkedin-os weekly-review
```

Use `data/samples/performance.csv` as a schema example only. Weekly review reports patterns and never changes the rubric automatically.

## Approval package

Every successful draft run creates exactly:

```text
outputs/YYYY-MM-DD/<slug>/
  brief.md
  candidates.md
  critic.json
  final-package.md
  sources.md
```

`STATUS: READY FOR HUMAN APPROVAL` means only that structural checks passed. Abhillash must verify sources, edit, approve, and publish manually.

See [ARCHITECTURE_DECISION.md](ARCHITECTURE_DECISION.md), [RECOVERY_MANIFEST.md](RECOVERY_MANIFEST.md), and [docs/WORKFLOW.md](docs/WORKFLOW.md) for boundaries and provenance.
