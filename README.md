# LinkedIn Authority OS v6

This repository preserves the evidence-backed role, voice, and rubric assets recovered for LinkedIn Authority OS v6 and provides a deliberately small offline runtime foundation.

The intended workflow boundary is Scout → Analyst → Writer → Critic → human approval. Historical Gmail ingestion, authenticated browser analytics, schedulers, messaging, and publishing-adjacent components are deliberately excluded.

## Offline quick start

Requires Python 3.11 or newer and no third-party packages.

```sh
make setup
make doctor
./bin/linkedin-os research --dry-run
./bin/linkedin-os draft --dry-run
make test
```

`research --dry-run` validates and stores the visibly synthetic fixture in the ignored SQLite research ledger. Canonical URL and normalized body hash are independent uniqueness keys, so rerunning the command is safe. `draft --dry-run` currently validates the fixture envelope but does not generate an approval package.

Private JSON, JSONL, and NDJSON imports belong under ignored `data/private/`:

```sh
./bin/linkedin-os research --input data/private/research.jsonl
```

Each item needs a public HTTP(S) URL, title, publisher/source, timestamp, and `primary|secondary|mixed` quality; body and author are optional. Live source collection fails honestly until the safe model boundary is added.

See [ARCHITECTURE_DECISION.md](ARCHITECTURE_DECISION.md) for the current boundary and [RECOVERY_MANIFEST.md](RECOVERY_MANIFEST.md) for provenance.

Automatic LinkedIn publishing is absent and remains out of scope.
