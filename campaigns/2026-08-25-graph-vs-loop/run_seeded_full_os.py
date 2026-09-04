#!/usr/bin/env python3
"""Run one supplied LinkedIn draft through the complete campaign day pipeline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Mapping, Sequence

from authority_os import anti_slop, campaign, workflow


SEED_POST = """I’ve stopped drawing agent graphs until the workflow proves it needs one.

So I built Agent Graph Designer to make that call before any topology exists.

It’s 100% free, MIT licensed and runs locally.

https://github.com/Abhillashjadhav/AI-PM-essential-skills/tree/main/agent-graph-designer

Then I ran Loop Engineering and Graph Engineering against the same frozen market snapshot: 12 real U.S. large-cap stocks, captured on August 25.

The task was simple. Prioritize three companies for deeper research using earnings power, valuation, scale and liquidity.

The loop compressed those signals into one weighted score. It ranked META first, LLY second and GOOGL third.

The graph kept the four checks independent and joined their records at the end. It returned GOOGL, META and MSFT.

LLY explains the difference. Its EPS gave it the strongest earnings-power score in the universe, so the loop carried it to second place. But its P/E was 42.17, above the graph’s valuation-risk limit of 40. That branch failed, the disagreement stayed visible, and LLY was excluded.

For this configured broad screen, the graph produced the better output.

The loop still has the next job. Once the graph gives me the shortlist, I’d use a loop to take one company through deeper diligence.

That’s the boundary I wanted the tool to make explicit.

These are research candidates from one dated screen, not investment recommendations."""


def build_day() -> dict[str, object]:
    return campaign._safe_day(
        {
            "day": "Tuesday",
            "date": "2026-08-25",
            "topic": "Graph Engineering versus Loop Engineering",
            "topic_slug": "graph-versus-loop-engineering",
            "thesis": (
                "A graph earns its complexity when independent evidence paths must preserve "
                "disagreement; one loop is better when a single objective improves through "
                "sequential critique."
            ),
            "target_reader": (
                "AI product leaders and AI engineers choosing an execution architecture for "
                "multi-step research workflows"
            ),
            "reader_problem": (
                "AI product leaders need to know when one iterative loop is sufficient and when "
                "independent evidence paths need a graph that preserves disagreement."
            ),
            "product_decision": (
                "Use a graph for the broad screen and a loop for deeper diligence on one "
                "shortlisted company."
            ),
            "authority_statement": (
                "Connect workflow topology to an explicit product decision about preserving "
                "disagreement in agent research."
            ),
            "why_now": (
                "Agent Graph Designer now makes the loop-versus-graph qualification explicit, "
                "and the dated comparison supplies one inspectable run."
            ),
            "dominant_take": (
                "Architecture discussions often compare diagrams instead of showing how the same "
                "input produces a different decision."
            ),
            "missing_angle": (
                "Use the supplied post as working material. Revise it rather than treating it as "
                "approved prose. Preserve the human voice, expose the exact LLY disagreement, and "
                "keep the result bounded to this configured run."
            ),
            "artifact_policy": (
                "Return NONE. A separately verified side-by-side video already carries the visual "
                "comparison; do not generate a competing artifact."
            ),
            "evidence": [
                {
                    "id": "source-1",
                    "title": "Agent Graph Designer loop-versus-graph qualification",
                    "claim": (
                        "The public Agent Graph Designer repository says it first decides whether "
                        "a graph is justified. When one loop is enough, it returns LOOP_SUFFICIENT; "
                        "when coordination is the problem, it returns GRAPH_REQUIRED. The "
                        "repository says graph complexity must earn its cost and uses the MIT License."
                    ),
                    "source": (
                        "https://github.com/Abhillashjadhav/AI-PM-essential-skills/"
                        "tree/main/agent-graph-designer"
                    ),
                    "source_quality": "primary",
                    "body_read": True,
                    "source_date": "2026-08-19",
                    "date_kind": "accessed",
                    "caveats": (
                        "Author-owned repository evidence establishes the public design and license, "
                        "not adoption or comparative performance."
                    ),
                },
                {
                    "id": "source-2",
                    "title": "Graph and loop engineering frozen market-data run",
                    "claim": (
                        "A frozen market-data lookup captured on 2026-08-25 at 15:59 UTC covered "
                        "12 real U.S. large-cap equities. The loop weighted "
                        "earnings power at 65% and ranked META first, LLY second, and GOOGL third. "
                        "The graph used independent earnings-power, valuation, scale, "
                        "and liquidity branches with a minimum three-of-four pass rule and a P/E "
                        "risk limit of 40; it ranked GOOGL first, META second, and MSFT third. LLY "
                        "had EPS 29.80 and P/E 42.17; it ranked second in the loop and was excluded "
                        "by the graph."
                    ),
                    "source": "https://www.nasdaq.com/market-activity/stocks/screener",
                    "source_quality": "mixed",
                    "body_read": True,
                    "source_date": "2026-08-25",
                    "date_kind": "accessed",
                    "caveats": (
                        "The URL is a public market-screener reference. The values are a frozen "
                        "lookup captured for this run, and the ranking depends on the disclosed "
                        "weights and thresholds. It is not investment advice."
                    ),
                },
            ],
        }
    )


def prepare_proof() -> workflow.LoadedProof:
    root = workflow.DEFAULT_PRIVATE_DATA / "graph-vs-loop-full-os"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    artifact = root / "ownership-attestation.md"
    manifest = root / "proof.json"
    artifact.write_text(
        "User-confirmed ownership and public-repository attestation for this post.\n",
        encoding="utf-8",
    )
    artifact.chmod(0o600)
    payload = {
        "schema_version": 1,
        "proof_id": "proof-agent-graph-designer",
        "proof_type": "repository",
        "artifact_path": artifact.name,
        "public_claim": (
            "I built and published Agent Graph Designer at "
            "https://github.com/Abhillashjadhav/AI-PM-essential-skills/tree/main/"
            "agent-graph-designer; it is free to use under the MIT License and runs as local "
            "repository code."
        ),
        "attested_personal_sentences": [
            "I’ve stopped drawing agent graphs until the workflow proves it needs one.",
            "So I built Agent Graph Designer to make that call before any topology exists.",
            "Once the graph gives me the shortlist, I’d use a loop to take one company through deeper diligence.",
            "That’s the boundary I wanted the tool to make explicit.",
        ],
    }
    manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    manifest.chmod(0o600)
    return workflow.load_proof_manifest(manifest)


def run(*, no_ai_slop: Path, output: Path, validate_only: bool) -> int:
    day = build_day()
    proof = prepare_proof()
    skill_path = no_ai_slop / "SKILL.md"
    eval_path = no_ai_slop / "eval.md"
    skill, evaluation, provenance = campaign._read_external_editor(skill_path, eval_path)
    brief = campaign._brief(day)
    evidence = campaign._runtime_evidence(day["evidence"])  # type: ignore[arg-type]
    seed_candidate = {
        "id": "seed-draft",
        "angle": "user-supplied-working-draft",
        "text": SEED_POST,
        "claim_ids": ["source-1", "source-2", proof.proof_id],
    }
    minimum, maximum = workflow.TEXT_WORD_LIMITS["authority"]
    seed_words = workflow.word_count(SEED_POST)
    if not minimum <= seed_words <= maximum:
        raise workflow.WorkflowError(
            f"Seed draft has {seed_words} words; authority requires {minimum}–{maximum}."
        )
    workflow.evaluate_candidate_gates(
        seed_candidate, brief=brief, evidence=evidence, proof=proof
    )
    if validate_only:
        print("VALID: seed, evidence, strategy, proof and external editor inputs loaded.")
        return 0

    original_writer = campaign._invoke_writer
    original_critic = campaign._invoke_critic
    original_gate = campaign._gate_candidate

    def seeded_writer(
        *,
        day: Mapping[str, object],
        brief: Mapping[str, object],
        evidence: Sequence[Mapping[str, object]],
        cycle: int,
        diagnostics: Sequence[Mapping[str, object]],
        config: campaign.ModelConfig,
        invoker: campaign.StageInvoker,
    ) -> list[dict[str, object]]:
        prompt = workflow.build_writer_prompt(
            brief=brief,
            evidence=evidence,
            voice_guidance=workflow.load_voice_guidance(),
            proof=proof,
        )
        retry = ""
        if diagnostics:
            retry = (
                "\n\nBOUNDED_REGENERATION_DIAGNOSTICS\n"
                + json.dumps(list(diagnostics), indent=2, sort_keys=True)
            )
        task = (
            f"Campaign day: {day['day']} ({day['date']}). Candidate cycle: {cycle}.\n"
            "Revise the supplied working draft into three materially different complete posts. "
            "Do not merely score it. Preserve the thesis, evidence boundary, human cadence, and "
            "bounded conclusion. First-person or ownership language is allowed only when copied "
            "exactly from an attested sentence in PUBLIC_PROOF, and that candidate must cite "
            f"{proof.proof_id}. Any sentence containing a product name, date, number, named status, "
            "or concrete mechanism must be copied verbatim from one cited evidence claim or the "
            "public proof claim.\n\n"
            f"{prompt}\n\nUSER_SUPPLIED_WORKING_DRAFT_UNTRUSTED\n{SEED_POST}\n"
            f"END_USER_SUPPLIED_WORKING_DRAFT_UNTRUSTED{retry}"
        )
        result = invoker(
            "writer", config, campaign._load_role("writer"), task, workflow.WRITER_SCHEMA
        )
        raw = result.get("candidates")
        if not isinstance(raw, list):
            raise workflow.WorkflowError("Campaign Writer response needs candidates.")
        return workflow.validate_draft_candidates(
            raw, brief=brief, evidence=evidence, proof=proof
        )

    def proof_aware_critic(
        *,
        candidates: Sequence[Mapping[str, object]],
        brief: Mapping[str, object],
        evidence: Sequence[Mapping[str, object]],
        config: campaign.ModelConfig,
        invoker: campaign.StageInvoker,
        stage: str = "critic",
    ) -> list[dict[str, object]]:
        if not candidates:
            return []
        task = workflow.build_critic_prompt(
            candidates=candidates,
            brief=brief,
            evidence=evidence,
            proof=proof,
        )
        result = invoker(
            stage,
            config,
            workflow.critic_scoring_system_prompt(),
            task,
            workflow.CRITIC_SCORE_SCHEMA,
        )
        validated = workflow.validate_critic_scorecards(
            result.get("scorecards"), candidates  # type: ignore[arg-type]
        )
        return workflow.rank_critic_scorecards(validated)

    def proof_aware_gate(
        candidate: Mapping[str, object],
        *,
        brief: Mapping[str, object],
        evidence: Sequence[Mapping[str, object]],
    ) -> dict[str, object]:
        return workflow.evaluate_candidate_gates(
            candidate, brief=brief, evidence=evidence, proof=proof
        )

    def invoker(
        stage: str,
        config: campaign.ModelConfig,
        role_prompt: str,
        task_prompt: str,
        schema: Mapping[str, object],
    ) -> dict[str, object]:
        if stage == "narrative_editor":
            task_prompt = task_prompt.replace(
                "Never introduce first-person, an author name, biography, or ownership phrasing.",
                (
                    "Preserve first-person only when the sentence is already present in the "
                    "candidate and supported by its proof claim ID; never invent biography or "
                    "ownership phrasing."
                ),
            )
        return campaign.default_stage_invoker(
            stage, config, role_prompt, task_prompt, schema
        )

    campaign._invoke_writer = seeded_writer
    campaign._invoke_critic = proof_aware_critic
    campaign._gate_candidate = proof_aware_gate
    try:
        output = output.resolve()
        try:
            output.relative_to(workflow.REPO_ROOT.resolve())
        except ValueError as exc:
            raise workflow.WorkflowError("Output must stay inside the LinkedIn repository.") from exc
        output.mkdir(parents=True, exist_ok=True)
        active_models = campaign.StageModels.preferred()
        trace = campaign._new_trace(
            day,
            models=active_models,
            editor_provenance=provenance,
            researched_at="2026-08-25T15:59:00Z",
        )
        try:
            trace = campaign._run_day(
                day,
                directory=output,
                models=active_models,
                invoker=invoker,
                skill=skill,
                evaluation=evaluation,
                editor_provenance=provenance,
                researched_at="2026-08-25T15:59:00Z",
                trace=trace,
            )
        except workflow.WorkflowError as exc:
            trace["final"] = {
                "status": "BLOCKED",
                "reason": str(exc),
                "human_approval_status": "NOT_APPROVED",
                "publishing_status": "DISABLED",
            }
        campaign._persist_day(output, trace)
    finally:
        campaign._invoke_writer = original_writer
        campaign._invoke_critic = original_critic
        campaign._gate_candidate = original_gate

    final = trace["final"]
    post_edit = trace.get("post_edit_recritic", {})
    score = post_edit.get("score", {}) if isinstance(post_edit, Mapping) else {}
    gates = post_edit.get("gates", {}) if isinstance(post_edit, Mapping) else {}
    result = {
        "final_status": final.get("status") if isinstance(final, Mapping) else "BLOCKED",
        "final_reason": final.get("reason") if isinstance(final, Mapping) else None,
        "critic_effective_total": score.get("effective_total") if isinstance(score, Mapping) else None,
        "hook_strength": score.get("hook_strength") if isinstance(score, Mapping) else None,
        "deterministic_gates": gates,
        "anti_slop_findings": post_edit.get("anti_slop_findings") if isinstance(post_edit, Mapping) else None,
        "regeneration_count": trace.get("regeneration_count"),
        "first_comment_score": (
            trace.get("first_comment", {}).get("review", {}).get("total")
            if isinstance(trace.get("first_comment"), Mapping)
            and isinstance(trace.get("first_comment", {}).get("review"), Mapping)
            else None
        ),
        "artifact_format": (
            trace.get("artifact", {}).get("format")
            if isinstance(trace.get("artifact"), Mapping)
            else None
        ),
        "visual_qa": (
            trace.get("visual_qa", {}).get("overall")
            if isinstance(trace.get("visual_qa"), Mapping)
            else None
        ),
        "output_directory": str(output),
        "human_approval_status": "NOT_APPROVED",
        "publishing_status": "DISABLED",
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if isinstance(final, Mapping) and final.get("status") == "READY_FOR_HUMAN_REVIEW":
        print("\nFINAL REVISED POST\n")
        print(final["post"])
        print("\nFIRST COMMENT\n")
        print(final["first_comment"])
        return 0
    return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--no-ai-slop",
        type=Path,
        default=Path("/tmp/no-ai-slop"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/2026-08-25/graph-vs-loop-full-os"),
    )
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    return run(
        no_ai_slop=args.no_ai_slop,
        output=args.output,
        validate_only=args.validate_only,
    )


if __name__ == "__main__":
    raise SystemExit(main())
