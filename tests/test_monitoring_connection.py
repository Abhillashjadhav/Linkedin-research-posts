"""Native export must preserve actual product behavior without any network call."""

from authority_os.monitoring_export import build_normalized_export
from test_monitoring_export import context


def decisions(run_id: str) -> list[dict[str, object]]:
    return [
        {"run_id": run_id, "recorded_at": "2026-08-30T12:00:00Z", "contract": contract,
         "status": "PASS", "subject_id": "candidate-1", "mode": "diagnostic",
         "evidence": {"observed_status": "FAIL", "cycle": cycle, "score": 3}}
        for contract, cycle in [("research_trust", 1), ("gate_citation", 1), ("gate_citation", 2)]
    ]


def test_explicit_identity_survives_run_change() -> None:
    first = dict(context(), case_id="frozen-input-1", input_fingerprint="sha256:" + "a" * 64,
                 comparison_sha256="sha256:" + "b" * 64)
    second = dict(first, run_id="linkedin-production-2")
    a = build_normalized_export(first, decisions(first["run_id"]))
    b = build_normalized_export(second, decisions(second["run_id"]))
    assert a["cases"][0]["case"] == b["cases"][0]["case"]
    assert a["comparison"]["sha256"] == first["comparison_sha256"]


def test_raw_advisories_and_cycles_survive_export() -> None:
    ctx = context()
    result = build_normalized_export(ctx, decisions(ctx["run_id"]))
    facts = result["source_facts"]
    citation = [f for f in facts if f["contract"] == "gate_citation"]
    assert [f["cycle"] for f in citation] == [1, 2]
    assert all(f["recorded_status"] == "PASS" and f["observed_status"] == "FAIL" for f in citation)
    checks = {c["definition_id"]: c for c in result["cases"][0]["checks"]}
    assert "claim-body-support" in checks
    assert checks["claim-body-support"]["status"] == "NOT_EVALUATED"
