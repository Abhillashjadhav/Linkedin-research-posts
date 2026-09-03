"""Build a blank human-golden worksheet from real campaign traces.

You score the posts. The judge's own scores are extracted separately so the two
label files can be compared without you seeing the judge's answer first.

  python3 make_goldens.py --campaigns ../../../campaigns --out worksheet.jsonl
"""
from __future__ import annotations
import argparse, json, pathlib

AXES = ["C_HOOK", "C_MIDDLE", "C_SPECIFICITY", "C_VOICE", "C_CLOSER"]
TRACE_AXES = {
    "C_HOOK": "hook_strength",
    "C_MIDDLE": "middle_escalation",
    "C_SPECIFICITY": "specificity_and_source_quality",
    "C_VOICE": "voice_fidelity",
    "C_CLOSER": "earned_closer",
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--campaigns", type=pathlib.Path, required=True)
    ap.add_argument("--out", type=pathlib.Path, default=pathlib.Path("worksheet.jsonl"))
    ap.add_argument("--judge-out", type=pathlib.Path, default=pathlib.Path("judge-labels.jsonl"))
    args = ap.parse_args()

    human, judge = [], []
    for trace_path in sorted(args.campaigns.rglob("trace.json")):
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
        cycles = (trace.get("critic") or {}).get("cycles") or []
        for cycle in cycles:
            cycle_no = cycle.get("cycle", 1)
            for card in cycle.get("scorecards", []):
                item_id = f"{trace_path.parent.name}-c{cycle_no}-{card['candidate_id']}"
                human.append({
                    "item_id": item_id,
                    "source": "human",
                    "split": "test",
                    "reviewer_id": "REPLACE_WITH_YOUR_ID",
                    "post_excerpt": (trace.get("final", {}).get("post") or "")[:280],
                    "labels": {"G_CRITIC_ADVANCE": "PASS_OR_FAIL"},
                    "scores": {axis: None for axis in AXES},
                })
                judge.append({
                    "item_id": item_id,
                    "judge_id": "linkedin-critic-v1",
                    "labels": {"G_CRITIC_ADVANCE": "PASS" if card.get("band") == "advance-to-gates" else "FAIL"},
                    "scores": {axis: card.get(field) for axis, field in TRACE_AXES.items()},
                })

    args.out.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in human))
    args.judge_out.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in judge))
    print(f"{len(human)} items -> {args.out} (score these by hand) and {args.judge_out}")


if __name__ == "__main__":
    main()
