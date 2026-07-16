# LinkedIn Authority OS v6

This repository currently preserves the evidence-backed role, voice, and rubric assets recovered for LinkedIn Authority OS v6. The recovery is intentionally provenance-first: every retained asset is classified as recovered, recovered and modified, reconstructed, or new in [RECOVERY_MANIFEST.md](RECOVERY_MANIFEST.md).

The preserved workflow boundary is Scout → Analyst → Writer → Critic → human approval. Historical Gmail ingestion, authenticated browser analytics, schedulers, messaging, and publishing-adjacent components are deliberately excluded. The reconstructed `/draft-post` coordinator is deferred until its CLI and output contract exist, so this snapshot contains no dangling executable instructions.

## Validate the recovery

Requires Python 3.11 or newer and no third-party packages.

```sh
python3 -m unittest discover -s tests -v
```

This recovery contribution contains no runtime or LinkedIn integration. Automatic publishing is absent and remains out of scope.
