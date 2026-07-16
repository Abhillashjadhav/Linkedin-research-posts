# LinkedIn Authority OS v6

This repository preserves the evidence-backed role, voice, and rubric assets recovered for LinkedIn Authority OS v6 and provides a deliberately small offline runtime foundation.

The intended workflow boundary is Scout → Analyst → Writer → Critic → human approval. Historical Gmail ingestion, authenticated browser analytics, schedulers, messaging, and publishing-adjacent components are deliberately excluded.

## Offline quick start

Requires Python 3.11 or newer and no third-party packages.

```sh
make setup
make doctor
./bin/linkedin-os draft --dry-run
make test
```

The dry run validates the envelope of visibly synthetic fixture data; research-item validation follows with ingestion. It does not generate an approval package. Live drafting fails with an actionable message until the research, analysis, drafting, Critic, and packaging outcomes land.

See [ARCHITECTURE_DECISION.md](ARCHITECTURE_DECISION.md) for the current boundary and [RECOVERY_MANIFEST.md](RECOVERY_MANIFEST.md) for provenance.

Automatic LinkedIn publishing is absent and remains out of scope.
