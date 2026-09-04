# Contract-first LinkedIn OS rebuild

```yaml
contract_id: linkedin-os-contract-first-rebuild-v1
problem: >-
  Repeated live runs fail at different stage boundaries, creating patch-by-patch
  QA and preventing dependable creation of a review-ready LinkedIn post.
hypothesis: >-
  A clean, contract-first local workflow with independently verified stages and
  explicit identity handoffs will remove integration drift and make operational
  failures recoverable without weakening product gates.
proposed_answer: >-
  Diagnose and correct the current evidence-Scout timeout while ten bounded
  architecture workstreams specify and build a replacement flow; integrate only
  after each stage passes its own contract, then replicate the proven workflow to
  GitHub.
target_outcome: >-
  One local command repeatedly completes discovery through final evaluation in
  seven to eight minutes and produces either a review-ready package or an exact,
  legitimate product-gate rejection rather than an integration or availability
  failure.
deadline: no explicit deadline; execute now in bounded stages
success:
  north_star: three consecutive live runs complete every executable stage without integration or availability failure
  leading:
    - every stage has an explicit input and output contract
    - every handoff uses stable identity rather than generated prose
    - evidence Scout timeouts recover within the total run budget
    - each stage has deterministic contract and failure-path tests
    - at least one live run produces a READY_FOR_HUMAN_REVIEW package
  guardrails:
    - honesty, citation, proof, privacy, relevance, and voice values gates never weaken
    - claim-support similarity remains 0.18
    - evidence must be body-verified and inside the requested seven-day window
    - an atomic value already published is never selected again
    - topic text never substitutes for evidence identity
    - no automatic approval, scheduling, or publication
    - failures and downstream NOT_EVALUATED stages remain observable
trade_off: reliability and evidence integrity within a hard seven-to-eight-minute latency budget
scope:
  - live discovery and momentum
  - evidence verification and bounded recovery
  - Topic Value and unpublished novelty
  - thesis generation and selection
  - exact evidence handoff
  - drafting, voice, Critic, and deterministic gates
  - observability, packaging, local orchestration, and release verification
non_goals:
  - automatic LinkedIn publishing
  - weakening thresholds to manufacture a passing run
  - authenticated social-network scraping
  - outcome-driven automatic rubric mutation
context_sources:
  - repository source, tests, configuration, documentation, and Git history
  - user decisions recorded in this project conversation
  - private live-run artifacts only when explicitly supplied
permissions:
  read: repository and user-supplied run artifacts
  local_write: rebuild branch, tests, and ignored local trial artifacts
  approval_required: push, pull request, merge, deployment, deletion, spending, or publication
definition_of_done:
  - ten task packets independently verified and joined through public entry points
  - current Scout timeout class has a tested bounded recovery path
  - three consecutive live trials meet the latency and identity contracts
  - GitHub replication is prepared but not pushed or merged without approval
approved_by: product owner; three consecutive live runs required for release success
```

## Product decisions already fixed

- Reuse is allowed only for body-verified evidence that remains inside the same
  requested seven-day window.
- Published atomic value is excluded from future selection; source reuse alone is
  not publication reuse.
- A legitimate quality or hard-gate rejection is a valid evaluated outcome. A
  timeout, signature mismatch, wrong-evidence retrieval, or hidden downstream stage
  is a system failure.
- Voice uses the measured v2 standard and remains an absolute acceptance gate at
  `voice_fidelity >= 4`.
- Acceptance remains five-axis total `>= 18`, with hook `>= 4`, voice `>= 4`, and
  middle escalation, earned closer, and specificity/source quality each `>= 3`.
- The separate first-comment score also has a total floor of `>= 18/25`; its
  different axes are not assigned the post's per-axis floors. Its existing
  evidence, anti-slop, and artisanal checks remain mandatory pending separate
  first-comment calibration.
- `18` is a floor, not a ceiling. Scores above 20 remain eligible when their
  route-specific gates pass. `24/25` may be an optimization target but is never
  an eligibility rule.
