---
name: draft-post
description: Produce one evidence-backed LinkedIn post for Abhillash. Use for /draft-post, today's post, or a requested topic.
---

# Draft Post

## Inputs
Optional topic, goal (`reach|authority|opportunity`), and format (`text|carousel|video`). Default goal is authority and default format is text.

## Execution
1. Read `docs/WORKFLOW.md`, `data/voice/voice-guide.md`, and `data/voice/abhillash-best-posts.md`.
2. Ask no follow-up when the topic and evidence are sufficient. When evidence is missing, research before drafting.
3. Route the goal:
   - reach: incident/humour/observation;
   - authority: mechanism/framework/trade-off;
   - opportunity: artifact/case study/proof.
4. Run Scout. Prefer primary sources. Store a short evidence brief with URLs and what each source supports.
5. Run Analyst. Produce one thesis using `Incident → Mechanism → Decision → Artifact`. Mark missing elements explicitly.
6. Run Writer. Produce three candidates with distinct hooks.
7. Run Critic. Reject unsupported claims and obvious AI voice. Permit one revision only.
8. Return the winner with:
   - copy-ready post;
   - goal and format;
   - evidence list;
   - critic score and remaining risk;
   - one suggested first comment only when useful.
9. Save to `drafts/YYYY-MM-DD-<slug>.md`.

## Human gate
Never publish automatically. Final output must say `STATUS: READY FOR HUMAN APPROVAL`.

## Quality bar
A post passes only when it contains original judgment, concrete evidence, and a clear reason for the target reader to remember Abhillash. Polished summarisation alone fails.