# Thursday capability discovery and post package

Thursday is the capability-discovery lane of the existing LinkedIn Research OS.
Find something a person can now do, show it working, and explain its practical
benefit in words the reader understands immediately. The objective is a useful,
surprising, shareable discovery. Neither a large model score nor observed
popularity guarantees the author's post will go viral.

## Routing and scope

The mode identifier is `thursday-capability-v1`. A supplied weekly slot of `3`
selects Thursday; when no slot is supplied, discovery can infer Thursday from its
`as-of` date in `Asia/Kolkata`. In a five-day campaign, the actual `Thursday` day
label selects this mode: Thursday is campaign day four, not array index three or
weekly slot four. Caller routing must reach the research, selection, writing,
first-comment and artifact stages. The user should not have to restate these rules.

This mode supersedes the incident-first preference for Thursday only. Keep other
weekday assignments, goal selection, score thresholds, consent requirements and
manual publication unchanged. A new independent skill or a separate campaign is
not required. Follow explicit topic or format instructions when supplied.

Implementation: [`thursday_capability.py`](../src/authority_os/thursday_capability.py).
For the existing execution and acceptance contracts, see
[`DISCOVERY_DECISION_MAP.md`](DISCOVERY_DECISION_MAP.md).

## Research: discover broadly, then inspect the capability

Start parallel discovery lanes where the runtime supports them:

- GitHub trending, release pages, changelogs and source repositories, including
  individual developers and small teams.
- Hacker News, especially Show HN; Hugging Face models, Spaces and release notes;
  public working demonstrations and research implementations.
- Public community discussion and creator posts to find emerging attention;
  primary launch pages and engineering documentation to verify the claim.

Query by useful capability as well as current date: a task now running locally,
an output generated interactively, a previously costly workflow made accessible,
or a new way to build, test or use AI. A frontier-company announcement is not a
prerequisite. News digests and trending lists are leads, not final evidence.

Do not spend Thursday's research budget looking mainly for outages, failures,
governance warnings, generic agent skills, prompt packs or courses. A familiar
category with a new label does not establish a new capability. An existing repo
can qualify when a substantive new release makes a previously unavailable useful
behavior possible; show what actually changed.

Discovery enforces a maximum seven-day capability window, measured against the
run's `as-of` date; a smaller requested window remains smaller. Record
the dates separately: coverage, original project, underlying model/paper, relevant
release, and when the capability became usable. An older repo with a meaningful
release this week must retain both dates. A current trending mention alone does
not turn an old capability into a new launch. An older underlying repo qualifies
only through an evidenced substantive current update. Historical examples that
received an exception are not automatic runtime exemptions: older capability
dates still fail this discovery eligibility check. Never relabel them to pass.
Never treat the oldest commit in a shallow clone as the first project commit.

Before final selection, sweep the last 48 hours for a stronger new candidate or a
material correction. Use the existing bounded research budget; if the sweep could
not be completed, record that limitation instead of claiming coverage.

## Separate attention from proof

Keep three independent records for a candidate:

| Record | What to capture | What it establishes |
|---|---|---|
| Capability evidence | Body-read primary docs/code, runnable instructions, output/demo, test conditions and limitations | What the project claims and what the visible demonstration actually shows |
| Attention observations | Public URL, timestamp, visible count, metric type, observation window, independent community/author | Where attention is observable |
| Freshness | Original date, relevant release date, article date, meaningful new behavior | Why this is timely |

Prefer corroborated attention on more than one public surface, but missing counts
are unknown, not zero. A star total is not star growth; growth requires comparable
dated observations or a reliable dated growth record. Reposts are not independent
reproductions. Do not invent likes, views, rank, acceleration, adoption, benchmark
results or virality. Creator footage is creator-reported evidence; do not call it
an independent test or imply the author ran the project.

## Selection: useful surprise before brand recognition

Compare the strongest supported candidates using the existing Topic Value and
momentum axes. Keep brief alternatives and the actual selection rationale in the
private review package. Do not add an unrelated scoring system or fabricate a
historical score for an accepted reference.

Apply these questions:

1. Can the reader's benefit be said in one plain sentence without a model name or
   jargon? What can the reader do that was harder, costlier or unavailable before?
2. Does real code execute and produce a visible result? Is the proof accessible,
   inspectable and attributable?
3. Does the result challenge an ordinary expectation without a fabricated claim?
   Prefer an understandable working surprise over a large unexplained number.
4. Is it timely, and is public attention observable? Preserve uncertainty about
   what is already familiar when post history is incomplete.
5. Can the reader try it, inspect it or make a concrete decision from it? Explain
   meaningful hardware, availability, licensing, cost and quality limitations.
6. Does it connect naturally to AI product work, reliability, evaluation or
   economics, without forcing a risk sermon or claiming personal ownership?

No single criterion proves future engagement. Do not choose a weaker unsupported
claim merely because its headline sounds more spectacular.

## Write the package as three complementary parts

| Part | Purpose | Requirements |
|---|---|---|
| Post | Let the reader understand the capability and benefit in-feed | Surprising supported output first, benefit immediately, minimal mechanism, honest limitation, one useful next action or earned question |
| First comment | Make the discovery inspectable and usable | Creator credit, canonical project and demo URLs where promised, prerequisites, concrete mechanism, optional relevant existing author asset |
| Demo/video | Show what happens | Real output early, source/recording provenance, readable demonstration, then only enough explanation to understand the result |

Do not withhold the reader's basic benefit behind a link. Do not imply that a
third-party repo is the author's work. Add the author's repo asset only when it
actually helps the reader test or use this capability; an irrelevant promotion
is not a required package component. A “project and demo in the first comment”
promise must have both working destinations in the comment. If explicit link
restrictions conflict, change the promise or provide an allowed destination.

Keep the accepted voice qualities: plain spoken language, a clear benefit,
specific evidence and an honest limitation. Avoid mechanical reuse of one hook,
reaction phrase or first-person anecdote. An enthusiastic opening can be tried
when the evidence earns it; enthusiasm cannot replace the supported fact. Keep
the existing goal-specific length contract and avoid padding with technical detail.

“Free,” “local,” “private” and “no API bill” each require separate evidence. A free
repository does not prove zero hardware cost, no model-license restrictions or no
external calls. Preserve test conditions and distinguish an output demonstration
from proof that it meets the reader's quality needs.

Verify the post, comment and visual against the same evidence: a simplification
rejected in the post must not reappear as a fact in its comment or animation. When
suggesting a trial, compare actual task correctness, usefulness and cost. Blind
indistinguishability of two answers alone does not prove either meets the task.

## Visual production and completion status

Prefer the original creator's permissible demo or a real, reproducible recording.
Show the result before a long title or diagram explanation. Where an explanatory
sequence adds value, use one coherent diagram with camera movement and close-ups
of its blocks, tied to visible output. Do not turn slide cards into an MP4 and
describe that as a working demonstration. Explanatory animation must be visibly
distinguished from recorded execution; it cannot establish performance or behavior.

Keep source media, editable files, dependency information, commands and sampled
review frames alongside produced assets in the private package. Check mobile
legibility, crop, transitions, timing, labels, attribution and claim consistency.
Review opening and closing frames and every meaningful change of state. Preserve
license and reuse information for outside footage and fonts.

Use the accepted production reference of 1920 × 1080, 30 fps and approximately
78 seconds unless an explicit brief calls for different dimensions or pacing.
These are production settings, not evidence that the renderer has run.

An artifact plan, SVG storyboard or renderer instructions do not establish that
an MP4 exists or plays correctly. Record the delivered state honestly: original
demo reference, editable plan, rendered asset, or verified video. If production is
blocked, retain the grounded post/comment and identify the specific missing media,
dependency or verification. Do not substitute a stale asset from a previous run.

The campaign path retains `post.md` and `first-comment.md` and writes
`video-production-handoff.md` for an unrendered Thursday plan. `trace.json` and
`summary.md` expose completion state: a `PLAN_ONLY` / `NOT_RENDERED` artifact and
`NOT_EVALUATED` visual review must leave the full Thursday package incomplete,
with `COMPLETED_WITH_WARNINGS` where a grounded post is retained. These outputs
make production requirements reviewable; they are not evidence of a finished MP4.

The standalone `--package` path has eight current files (legacy packages may have
six). It includes `post.md` and `source-comment.md`; the latter is a grounded
companion assembled from validated capability metadata. Its editorial score is
`NOT_EVALUATED`, not a claimed first-comment Critic pass. `final-package.md` and
`evaluation.json` carry the source-linked actionable video plan and full-package
`INCOMPLETE` status until actual media is rendered and verified. Keep the
standalone companion's provenance checks separate from campaign editorial review.

## Review and repeat

Use the active writing contract: total at least 17/25, hook and voice at least 4/5,
and middle, closer and specificity at least 3/5. Preserve the separate first-comment
contract. Historical /50 rubrics are reference material, not runtime acceptance.
An accepted writer revision is a style reference; a high scoring rejected hook is
not a template that overrides it. On bounded exhaustion retain the grounded draft
with honest warnings, following the current runtime.

Deliver the finished private review package without adding a new mandatory topic
approval round: selected topic, concise alternatives, freshness and attention
evidence, post, first comment with its actual review status, demo/provenance and
actual asset status.
Do not silently change the goal to maximize likes. Publication remains manual.

After confirmed publication, use existing performance learning with comparable
measurement windows. Separate reported positive response from measured results;
compare like-for-like posts and capture edits the owner accepted or rejected.
Treat explanations for engagement as hypotheses. Improve topic choices and
packaging without declaring that one successful post proves a universal formula.

Reference PDFs, private conversations, source archives and performance records
remain private. This public workflow captures reusable instructions without
copying the owner's private post text, personal history or unpublished analytics.
