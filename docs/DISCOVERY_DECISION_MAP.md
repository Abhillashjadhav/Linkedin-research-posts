# Where LinkedIn discovery decisions actually run

Audit: 2026-09-08. Scope: the public `bin/linkedin-os discover --generate-post`
entry point, its installed runtime overrides, ranking/evidence contracts, and the
child drafting command. This is a code-path audit, not a live provider trial.

## What stopped the 12:29 run

The supplied dashboard reports `Authority topic critic timed out.` Four surface
scouts returned 20 signals. The run stopped during the optional authority-fit
ranking call, before source verification, Topic Value, thesis selection, or writing.
It did not fail the one-primary-or-three-credible-sources rule.

The preceding ranking change expanded the authority request from five topics to
the full pool, but `momentum.authority_topic_schema()` still required exactly five
scorecards while `validate_authority_scores()` required every requested topic.
That was an implementation error in the ranking change. It makes a ten-topic
request internally inconsistent. The screenshot establishes a timeout; it does
not establish whether the provider stalled because of this schema mismatch.

## Three different meanings of authority and coverage

| Concept | Question | Inputs |
|---|---|---|
| Conversation coverage | Where was a topic discussed? | Public scout signals and observed momentum |
| Authority fit | Can this topic support useful product judgment? | Audience, supplied public signals, five ranking axes; no author proof prerequisite |
| Source credibility/coverage | What supports this particular situation? | Read source bodies and their provenance |

Four successful scout lanes do not mean four corroborating sources for one claim.
One relevant body-read primary source satisfies coverage. Otherwise three distinct
body-read credible URLs must support that same situation. Adding unrelated links
does not establish coverage. Coverage is currently advisory, whereas malformed or
missing source references remain errors.

## Runtime composition

`bin/linkedin-os` installs `v1_gates`, `v1_completion`, and
`topic_value_id_contract` before importing `daily_discovery_cli`.
That composition root installs `discovery_runtime_tuning`,
`surface_scout_runtime_tuning`, `individual_launch_runtime_tuning`, and
`v1_consumability`, then assigns `daily_spine_cli.momentum` to
`momentum_surface_parallel`. Several `install()` functions replace module functions.
Reading the uninstalled base module or the JSON product contract alone therefore
does not establish live behavior.

When discovery invokes `bin/linkedin-os draft`, the child additionally installs
the length, single-topic model, readability, critic-anchor retry, actionable
diagnostics, social-policy, consumability, runtime tuning, quality optimizer, and
standalone-observability modules listed in that launcher. The active writing
coordinator is `quality_optimizer` over the integrated draft command.

## Decision map

| Boundary | Executable owner | Actual decision |
|---|---|---|
| Discovery window | `daily_cli.parser`, `daily_spine_cli.command` | Seven days by default; source dates are checked against the requested window. |
| Scout availability | `surface_scout_runtime_tuning._run_surface` | 180 seconds per lane, at most two attempts for timeout/unavailability. Missing lanes are reported. |
| Consolidation | `momentum_surface_parallel.invoke_scout`, `v1_consumability._consolidate` | Return one to six meaningful conversations. Aim for five or six when supported; never pad the list. Fewer than four lanes is a visible warning. Missing engagement stays unknown. |
| Momentum scoring | `momentum.validate_candidates`, `momentum.rank_candidates` | Deterministic observed-axis scores; fewer than four observed axes yields an unknown total. Unknown evidence is not a zero score. |
| Authority-fit scoring | `momentum.score_authority_fit` | Full pool in batches of at most five; schema cardinality matches each batch; 120-second deadline per call. IDs and scores remain strictly validated. |
| Authority timeout recovery | `daily_spine_cli.command`, `model_runtime.ModelTimeoutError` | Save `discovery-ranked.json` before scoring. On a deadline only, preserve topics, mark authority unavailable, continue with a visible warning. Other provider/schema errors still stop. |
| Retained pool | `daily_spine_cli.update_candidate_inventory`, `select_topic_scope` | Fresh and unexpired candidates compete without 14/40 score cutoffs. Normally compare combined momentum/authority scores. If authority is missing, compare the common observed momentum basis across the pool; never compare a 25-point total directly to a 50-point total or invent authority scores. |
| Evidence retrieval | `daily_spine_cli.resolve_signal_evidence` | Reuse matching verified evidence, then bounded targeted acquisition. Require actual bodies, usable provenance, valid URLs and dates; one to seven verified sources are allowed. |
| Source coverage | `v1_gates.evaluate_research_trust` | One relevant body-read primary source OR three distinct body-read credible URLs; advisory when short. Topic/thesis schemas now allow up to seven references, so the three-source route is representable. |
| Topic selection | `topic_value.invoke_discovery_selector`, `v1_gates._evaluate_topic_candidates` | Rank existing axes; keep reader-value/goal eligibility. Exclude repeated/unverified atomic ideas individually, then choose the highest-scoring remaining candidate. |
| Novelty history | `v1_completion.load_published_atomic_values` | Compare with recorded confirmed publication history. An empty history cannot establish that an idea has never been published. |
| Thesis selection | `daily_spine_cli.search_theses`, `daily_cli.validate_cards` | One valid three-card batch, same five ranking axes, no 23-point threshold or score retries. Valid public evidence IDs, distinct thesis text and short summaries are required. New cards use the compatibility field proof_id=NOT_REQUIRED; no proof inventory is required. |
| Writing acceptance | `acceptance_policy`, `quality_optimizer`, `eval_package` | Hook and voice >=4; middle, closer and specificity >=3 (minimum total 17). Stop immediately. Before then, accept only a higher total with reduced deficits and no individual axis decrease; otherwise keep the prior draft. Exhaustion delivers it with warnings. |
| Candidate findings in UI | `v1_completion._record_topic_decisions`, `daily_spine_cli.render_eval_dashboard` | Preserve all candidate findings; selected-topic decisions determine its current verdict. `eval_dashboard_html` renders shadow findings as advisory. |
| Human publication | `bin/linkedin-os`, approval/package boundaries | Generating a draft does not publish it to LinkedIn. |

## Corrections and remaining limits

This change fixes the authority request/schema mismatch, introduces a specific
timeout recovery path, checkpoints retrieved topics, and removes the two-reference
cap that contradicted the three-source coverage rule. It does not mark a timeout
as a successful authority evaluation, and it does not manufacture source evidence.

The owner's subsequent simplification is now implemented:

- Consolidation accepts up to six conversations, including smaller genuine pools.
  When momentum is incomplete but all authority scores are available, rank on that
  common authority basis and label it; never invent engagement or mix 25- and
  50-point scales. A pool with neither usable score basis still cannot be ranked.
- The owner confirmed 17 as the sum of the five required axis minima and strict
  score increases before acceptance. Equal-total trades and any axis decrease
  cannot replace the retained draft, even if other scores improve. Both writing
  paths stop immediately at the minima; no optional polish is run afterward.
- Author proof is no longer a discovery input requirement. Old inventories and
  valid proof references remain readable for compatibility, but new thesis
  generation requests NOT_REQUIRED and does not send the inventory to the judge.
  The legacy proof_fit axis now means public-evidence grounding. This does not
  authorize fabricated personal achievements or replace factual source checks.

The private checkpoint records work; it is not a claim that the existing
`--resume-from` command can resume an arbitrary stage. That command still supports
the documented evidence-verification recovery boundary.

## Verification boundary

Regression checks exercise 1/5/7/10-topic authority request cardinality, timeout
classification, topic retention and continued drafting after a simulated authority
timeout, and a three-source situation through validation and coverage evaluation.
The installed command tests cover composition overrides. These tests do not prove
provider availability or the quality of a future generated post.
