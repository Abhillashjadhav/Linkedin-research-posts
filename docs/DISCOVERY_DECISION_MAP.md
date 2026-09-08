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
| Author authority fit | Can this author contribute something useful? | Audience, public-safe proof inventory, five ranking axes |
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
| Consolidation | `momentum_surface_parallel.invoke_scout`, `v1_consumability._consolidate` | Still requires at least ten signals and exactly ten clusters; fewer than four lanes is only a warning when sufficient signals exist. This count constraint is separate from source credibility. |
| Momentum scoring | `momentum.validate_candidates`, `momentum.rank_candidates` | Deterministic observed-axis scores; fewer than four observed axes yields an unknown total. Unknown evidence is not a zero score. |
| Authority-fit scoring | `momentum.score_authority_fit` | Full pool in batches of at most five; schema cardinality matches each batch; 120-second deadline per call. IDs and scores remain strictly validated. |
| Authority timeout recovery | `daily_spine_cli.command`, `model_runtime.ModelTimeoutError` | Save `discovery-ranked.json` before scoring. On a deadline only, preserve topics, mark authority unavailable, continue with a visible warning. Other provider/schema errors still stop. |
| Retained pool | `daily_spine_cli.update_candidate_inventory`, `select_topic_scope` | Fresh and unexpired candidates compete without 14/40 score cutoffs. Normally compare combined momentum/authority scores. If authority is missing, compare the common observed momentum basis across the pool; never compare a 25-point total directly to a 50-point total or invent authority scores. |
| Evidence retrieval | `daily_spine_cli.resolve_signal_evidence` | Reuse matching verified evidence, then bounded targeted acquisition. Require actual bodies, usable provenance, valid URLs and dates; one to seven verified sources are allowed. |
| Source coverage | `v1_gates.evaluate_research_trust` | One relevant body-read primary source OR three distinct body-read credible URLs; advisory when short. Topic/thesis schemas now allow up to seven references, so the three-source route is representable. |
| Topic selection | `topic_value.invoke_discovery_selector`, `v1_gates._evaluate_topic_candidates` | Rank existing axes; keep reader-value/goal eligibility. Exclude repeated/unverified atomic ideas individually, then choose the highest-scoring remaining candidate. |
| Novelty history | `v1_completion.load_published_atomic_values` | Compare with recorded confirmed publication history. An empty history cannot establish that an idea has never been published. |
| Thesis selection | `daily_spine_cli.search_theses`, `daily_cli.validate_cards` | One valid three-card batch, same five ranking axes, no 23-point threshold or score retries. Valid evidence IDs, proof IDs, distinct thesis text and short summaries are still required. |
| Writing acceptance | `acceptance_policy`, `quality_optimizer` | Total >=18; hook and voice >=4; middle, closer and specificity >=3. Best-draft delivery preserves unmet-score warnings. Real execution/private-data errors can still stop delivery. |
| Candidate findings in UI | `v1_completion._record_topic_decisions`, `daily_spine_cli.render_eval_dashboard` | Preserve all candidate findings; selected-topic decisions determine its current verdict. `eval_dashboard_html` renders shadow findings as advisory. |
| Human publication | `bin/linkedin-os`, approval/package boundaries | Generating a draft does not publish it to LinkedIn. |

## Corrections and remaining limits

This change fixes the authority request/schema mismatch, introduces a specific
timeout recovery path, checkpoints retrieved topics, and removes the two-reference
cap that contradicted the three-source coverage rule. It does not mark a timeout
as a successful authority evaluation, and it does not manufacture source evidence.

Three additional constraints remain visible in the map rather than being silently
treated as evidence failures:

- The discovery consolidation model still expects ten conversations. A day with
  fewer signals can stop even if one topic has excellent primary evidence.
- `acceptance_policy.repair_score_decision` still refuses any decrease in total,
  including an edit that improves hook or voice. This can conflict with an intended
  trade between already-strong non-priority axes and weak priority axes. It was not
  exercised in the supplied timeout run, and this timeout/source-contract patch
  does not change writing-repair policy.
- `daily_cli.validate_profile` requires a nonempty author proof inventory, and
  every thesis must cite a valid proof ID. The product contract describes author
  proof as conditional for evidence-led posts. That conditional behavior is not
  implemented by these validators; primary-source credibility alone does not
  satisfy the separate author-profile requirement.

The private checkpoint records work; it is not a claim that the existing
`--resume-from` command can resume an arbitrary stage. That command still supports
the documented evidence-verification recovery boundary.

## Verification boundary

Regression checks exercise 1/5/7/10-topic authority request cardinality, timeout
classification, topic retention and continued drafting after a simulated authority
timeout, and a three-source situation through validation and coverage evaluation.
The installed command tests cover composition overrides. These tests do not prove
provider availability or the quality of a future generated post.
