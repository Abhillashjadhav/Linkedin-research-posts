from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from authority_os import storage, workflow
from scripts import compare_capture_runtime


class FrozenEvidenceComparisonTests(unittest.TestCase):
    TOPIC = "Controlling the production economics of agentic workloads"
    RAW_ITEMS = (
        {
            "url": "https://example.com/budgets",
            "title": "Project spending limits for AI APIs",
            "body": "Hard spending limits pause calls when the budget is exhausted.",
            "source": "Example One",
            "published_at": "2026-08-26T13:30:06Z",
            "source_quality": "secondary",
        },
        {
            "url": "https://example.com/routing",
            "title": "Traffic-shaped model routing",
            "body": "Production traffic can inform model selection and caching.",
            "source": "Example Two",
            "published_at": "2026-08-28T05:00:53Z",
            "source_quality": "secondary",
        },
        {
            "url": "https://example.com/cpus",
            "title": "CPU orchestration and idle accelerators",
            "body": "CPU-bound tool calls can leave accelerators idle.",
            "source": "Example Three",
            "published_at": "2026-08-25T10:41:54Z",
            "source_quality": "secondary",
        },
    )

    def _write_frozen(self, root: Path) -> Path:
        path = root / "research.json"
        path.write_text(json.dumps({"items": self.RAW_ITEMS}), encoding="utf-8")
        return path

    def test_normal_analysis_is_unchanged_but_explicit_comparison_succeeds(self) -> None:
        prepared = workflow.prepare_research_items(
            self.RAW_ITEMS, fetched_at="2026-08-29T00:00:00Z"
        )
        with self.assertRaisesRegex(workflow.WorkflowError, "No research cluster matches"):
            workflow.analyse_research(prepared, topic=self.TOPIC)

        with tempfile.TemporaryDirectory() as temporary:
            frozen = self._write_frozen(Path(temporary))
            before = frozen.read_bytes()
            original_theme = workflow._theme_for  # type: ignore[attr-defined]
            original_build = workflow.build_drafting_evidence
            original_list = storage.list_research_items
            try:
                with patch.object(storage, "list_research_items", return_value=prepared):
                    trace = compare_capture_runtime._install_frozen_evidence_routing(  # type: ignore[attr-defined]
                        frozen_research=frozen,
                        frozen_topic=self.TOPIC,
                    )
                    rows = storage.list_research_items(
                        "unused.db",
                        topic_terms=workflow.topic_prefilter_terms(self.TOPIC),
                        evidence_origins=("private-import",),
                    )
                    analysis = workflow.analyse_research(rows, topic=self.TOPIC)
                    selected = analysis["pass_2"]["selected"]
                    evidence = workflow.build_drafting_evidence(
                        rows, topic_slug=str(selected["slug"])
                    )
                    compare_capture_runtime._assert_frozen_research_unchanged(  # type: ignore[attr-defined]
                        frozen, trace
                    )
                    self.assertEqual(frozen.read_bytes(), before)
            finally:
                workflow._theme_for = original_theme  # type: ignore[attr-defined]
                workflow.build_drafting_evidence = original_build
                storage.list_research_items = original_list

        self.assertEqual(len(evidence), 3)
        self.assertEqual([item["id"] for item in evidence], ["source-1", "source-2", "source-3"])
        self.assertTrue(trace["input_unchanged"])

        # The opt-in observer patch is process-local; restoring it preserves normal V0.
        with self.assertRaisesRegex(workflow.WorkflowError, "No research cluster matches"):
            workflow.analyse_research(prepared, topic=self.TOPIC)

    def test_v0_and_v1_routes_have_identical_ids_and_hashes(self) -> None:
        prepared = workflow.prepare_research_items(
            self.RAW_ITEMS, fetched_at="2026-08-29T00:00:00Z"
        )
        traces: list[dict[str, object]] = []
        with tempfile.TemporaryDirectory() as temporary:
            frozen = self._write_frozen(Path(temporary))
            for _label in ("v0", "v1"):
                original_theme = workflow._theme_for  # type: ignore[attr-defined]
                original_build = workflow.build_drafting_evidence
                original_list = storage.list_research_items
                try:
                    with patch.object(storage, "list_research_items", return_value=prepared):
                        trace = compare_capture_runtime._install_frozen_evidence_routing(  # type: ignore[attr-defined]
                            frozen_research=frozen,
                            frozen_topic=self.TOPIC,
                        )
                        rows = storage.list_research_items(
                            "unused.db",
                            topic_terms=("agentic",),
                            evidence_origins=("private-import",),
                        )
                        analysis = workflow.analyse_research(rows, topic=self.TOPIC)
                        workflow.build_drafting_evidence(
                            rows,
                            topic_slug=str(analysis["pass_2"]["selected"]["slug"]),
                        )
                        traces.append(trace)
                finally:
                    workflow._theme_for = original_theme  # type: ignore[attr-defined]
                    workflow.build_drafting_evidence = original_build
                    storage.list_research_items = original_list

        self.assertEqual(traces[0]["input_sha256"], traces[1]["input_sha256"])
        self.assertEqual(traces[0]["record_hashes"], traces[1]["record_hashes"])
        self.assertEqual(traces[0]["content_hashes"], traces[1]["content_hashes"])
        self.assertEqual(traces[0]["writer_evidence"], traces[1]["writer_evidence"])


if __name__ == "__main__":
    unittest.main()
