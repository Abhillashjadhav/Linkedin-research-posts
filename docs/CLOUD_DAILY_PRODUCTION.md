# Cloud daily production

The daily Authority OS can run on GitHub Actions without the user's Mac being online.

## What runs in the cloud

The scheduled workflow uses the real repository CLI:

```text
public-web conversation discovery
→ momentum ranking
→ authority fit
→ three cleared thesis cards
→ high-bar draft loop for thesis 1
→ high-bar draft loop for thesis 2
→ high-bar draft loop for thesis 3
→ one-day Actions artifact for human review
```

Each draft keeps the existing live quality contract: effective Critic score at least 24/25, hook exactly 5/5, required deterministic gates, integrated anti-slop, bounded regeneration, manual fact verification, and publishing disabled.

The workflow never publishes, comments, messages, or authenticates to LinkedIn.

## Schedule

`.github/workflows/daily-production.yml` starts at 22:30 UTC, approximately 04:00 IST the following morning. `workflow_dispatch` is also available for a manual cloud run.

GitHub schedules can start later than the exact cron minute when the hosted runner queue is busy, so the workflow deliberately starts well before the morning review window.

## One-time credential setup

The GitHub runner cannot reuse the ChatGPT/Codex login stored on a Mac. Create a repository Actions secret named:

```text
OPENAI_API_KEY
```

Codex CLI supports API-key authentication through the `OPENAI_API_KEY` environment variable. API usage is billed through the selected OpenAI API account; a ChatGPT Pro subscription and API billing are separate.

Do not commit the key to the repository, a workflow file, a profile, a trace, or an artifact.

If the secret is absent, the workflow exits before any model work.

## Public-safe profile

Cloud execution uses `data/cloud/authority-profile.json`. It contains only reviewed public-safe positioning and repository proof claims. The workflow copies that file into ignored `data/private/` at runtime because the normal discovery pipeline intentionally accepts private runtime inputs only.

No file from the user's laptop is required.

## Output

Each run creates an ignored runtime bundle under:

```text
data/private/cloud-daily/<github-run-id>-<attempt>/
```

It contains:

- `manifest.json` with run/draft statuses;
- the persisted momentum and thesis package;
- three strategy files;
- discovery stdout/stderr;
- one stdout/stderr trace for each of the three high-bar draft runs;
- the private research SQLite database used by that isolated run.

The workflow uploads that run directory as a GitHub Actions artifact with one-day retention and never commits generated posts or traces back to the public repository.

Because this repository is public, treat the Actions artifact as a short-lived review transport rather than a long-term private archive. Do not put unreviewed confidential company information or private personal evidence into the tracked cloud profile.

## Morning workflow

The laptop is not part of execution. In the morning, review the completed three-post bundle, inspect scores and failed/pass cycles, perform any external LLM verification desired, review the first-comment/collateral layer, and publish manually outside the system.

Human approval and LinkedIn publication remain outside Authority OS.
