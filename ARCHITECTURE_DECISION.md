# Architecture decision: minimal offline runtime

Status: **accepted**

LinkedIn Authority OS starts with one fixed `linkedin-os` entry point and one small standard-library workflow module. The initial runtime supports idempotent local setup, secret-safe diagnostics, and deterministic fixture validation. It deliberately does not draft live content or generate an approval package yet.

## Current boundary

- Python 3.11+ standard library only; setup downloads nothing.
- `bin/linkedin-os` is the only executable entry point.
- `src/authority_os/__main__.py` owns fixed command routing.
- `src/authority_os/workflow.py` owns the synthetic fixture contract.
- Private state and generated outputs are ignored from Git.
- There is no database, model invocation, network access, scheduler, browser automation, or LinkedIn write surface in this snapshot.

The runtime will grow only when a later atomic contribution adds a tested product outcome. No agent framework, command bus, service layer, or plugin abstraction is justified.
