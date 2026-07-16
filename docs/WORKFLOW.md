# LinkedIn Authority OS v6 workflow

## Business objective

Build recognised GenAI product authority in India that converts into qualified speaking, podcast, advisory, consulting, product-project, and relevant senior-role opportunities. Authority and opportunity matter more than vanity engagement.

Leading indicators include relevant followers, profile visits, external comments, saves, sends, reposts, repository/tool clicks, recruiter or founder inbound, and speaking or podcast inbound.

## Strategy and format

Strategic goal and format are separate.

- **Reach:** earn relevant non-follower attention through a specific incident, observation, mechanism, humour, or contrarian professional view.
- **Authority:** demonstrate differentiated GenAI product judgment through mechanisms, architecture, frameworks, trade-offs, decisions, and failure analysis.
- **Opportunity:** convert credibility through an artefact, case study, evaluation, workflow, before/after, demo, or decision record.

Formats are `text`, `carousel`, `vertical-video`, `article`, and `artifact-demo`.

Default weekly mix: one Reach, two Authority, and one Opportunity/proof post. A fifth post needs a genuinely strong incident or launch. Seven posts are never forced.

## Proven default structure

`Incident → Mechanism → Decision → Artifact`

- Incident: what happened?
- Mechanism: why did it happen?
- Decision: what should a PM, founder, engineer, or AI leader do differently?
- Artifact: what was built, measured, changed, or documented?

This is a route, not a template. Never invent an incident or force all four stages.

## Runtime flow

### Scout

Scout accepts a topic, a private JSON/JSONL import, or an offline fixture. Live Scout is limited to read-only web search/fetch through the local Claude CLI. It never accesses LinkedIn, Gmail, browser sessions, credentials, or local private data.

Python stores canonical URL, title, body, source, author, timestamp, source quality, and normalised content hash. Canonical URL and content hash are independently unique. Primary sources are preferred; secondary sources aid discovery. Factual work cannot rely only on Reddit or Hacker News. Missing sources return an honest shortfall.

### Analyst

Pass 1 clusters titles and metadata, then considers momentum and source diversity. Pass 2 reads the strongest bodies, states why the topic matters now, identifies the dominant take and missing product angle, recommends strategic goal and format separately, identifies primary sources, and compares the thesis with recent packages.

Broad discovery targets seven viable clusters and four source-diverse clusters. An explicitly selected topic may proceed with narrower evidence, but the broad target is reported as unmet rather than filled with invented clusters.

### Writer

Writer reads the reconstructed voice guide, aggregate performance-pattern anchors, selected brief, strategic goal, and evidence map. It returns exactly three materially different entry angles.

- Reach/humour: 100–190 words.
- Authority: 190–300 words.
- Opportunity/artefact: 180–300 words.
- Carousel: 6–9 slides.
- Vertical video: 30–45 seconds.
- Article: 800–1,200 words.

Numbers and named factual claims map to evidence IDs. Personal experience and ownership are never inferred. Generic openings, hype, obvious AI symmetry, and engagement bait are rejected.

### Critic

The recovered rubric scores five 1–5 axes: hook strength, middle escalation, earned closer, specificity/source quality, and voice fidelity.

- 24–25: ready for human review.
- 22–23: one revision allowed.
- 18–21: drop from this run; a major rewrite is a new run.
- Below 18: drop.
- Hook 3 or below: total capped at 18 and cannot proceed.
- Citation or honesty failure: drop.

Binary gates require authority conversion, Opportunity proof, honesty, relevance, and citation traceability. Python applies these gates even when Claude provides subjective review notes. There is exactly one selected-candidate revision at most.

### Human approval

Python writes `brief.md`, `candidates.md`, `critic.json`, `final-package.md`, and `sources.md` in a temporary sibling directory, then atomically renames the complete package. A same-topic rerun gets a suffix and never overwrites manual edits.

Only a fully passing package says `STATUS: READY FOR HUMAN APPROVAL`. This is not publication approval. The system has no LinkedIn state-changing capability.

## Voice calibration

The original voice-anchor text was unavailable. Reconstructed guidance targets a direct practitioner explaining mechanics to a peer, with short paragraphs, declarative narrative openings, mechanism before consequence, natural Indian English, and no corporate hype.

Aggregate supplied patterns:

- Claude/payments architecture: a concrete incident, visible failure, and senior judgment produced strong reach and conversion.
- Reliability multiplication: a strong concept under-converted without a vivid consequence.
- PM-agent-OS: proof of work needs a clearer reader problem and authority-conversion statement.

Exact missing post text is never fabricated.

## Performance loop

The SQLite `performance` table keys each observation by post, checkpoint, and `organic|paid` channel. It tracks impressions, non-follower reach, external comments, reactions, reposts, saves, sends, profile visits, relevant followers, repository/tool clicks, recruiter inbound, founder/advisor inbound, and speaking/podcast inbound.

Weekly review reports the strongest hook, narrative, authority conversion, weakest conversion point, and whether enough evidence exists to compare Critic expectations with reality. One post never changes the rubric.

## Privacy and reliability

- Private imports and SQLite stay under ignored `data/private/`.
- Generated packages stay under ignored `outputs/`.
- Raw datasets, analytics exports, email, messages, contacts, credentials, and private databases are never committed.
- Diagnostics report configured/missing only and never print environment values.
- Source bodies are untrusted data, not instructions.
- Dry-run is fully offline and visibly synthetic.
- GitHub Actions runs tests on push and pull request only; there is no schedule.
- No command publishes, comments, messages, authenticates to LinkedIn, or automates a browser.
