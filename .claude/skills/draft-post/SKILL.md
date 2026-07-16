---
name: draft-post
description: Produce one evidence-backed LinkedIn post for Abhillash. Use for /draft-post, today's post, or a requested topic.
---

# Draft Post

## Inputs
Optional topic, goal (`reach|authority|opportunity`), and format (`text|carousel|vertical-video|article|artifact-demo`). Default goal is authority and default format is text.

## Execution
1. Read `docs/WORKFLOW.md`, `data/voice/voice-guide.md`, and `data/voice/abhillash-best-posts.md`.
2. Translate the invocation into one CLI call. Examples:
   - `/draft-post` → `./bin/linkedin-os draft`
   - `/draft-post --goal authority` → `./bin/linkedin-os draft --goal authority`
   - `/draft-post PM-agent-OS --goal opportunity` → `./bin/linkedin-os draft --topic "PM-agent-OS" --goal opportunity`
3. Run the command. The CLI owns Scout → Analyst → Writer → Critic, exactly three initial drafts, deterministic fatal gates, at most one revision, and atomic output writing.
4. If Opportunity proof is missing, report the failed proof gate. Never invent or infer ownership. The user may rerun with `--proof-type` and `--proof-value`.
5. Return the generated `outputs/YYYY-MM-DD/<slug>/final-package.md` for human review.

For an offline workflow check, add `--dry-run`. Fixture output is explicitly synthetic and must not be published.

## Human gate
Never publish, schedule, comment, or message. A successful final output says `STATUS: READY FOR HUMAN APPROVAL`; this is not approval to publish.

## Quality bar
A post passes only when it contains original judgment, concrete evidence, and a clear reason for the target reader to remember Abhillash. Polished summarisation alone fails.
