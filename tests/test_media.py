from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path

from authority_os import media, workflow


class MediaTests(unittest.TestCase):
    def test_carousel_plan_requires_four_to_eight_slides(self) -> None:
        with self.assertRaisesRegex(workflow.WorkflowError, "4-8"):
            media.validate_plan(
                {
                    "media_type": "CAROUSEL_PDF",
                    "rationale": "Turn the decision into a reusable review artifact.",
                    "reader_job": "Use the review before production.",
                    "headline": "A simple agent approval check",
                    "visual_direction": "One decision per slide.",
                    "image_prompt": "",
                    "slides": ["One", "Two", "Three"],
                    "video_beats": [],
                    "alt_text": "Three-slide review",
                }
            )

    def test_media_command_requires_explicit_human_approval(self) -> None:
        args = argparse.Namespace(
            post_file=Path("missing.md"),
            topic="Agent budgets",
            output_dir=None,
            confirm_approved=False,
            allow_model_egress=True,
        )
        with self.assertRaisesRegex(workflow.WorkflowError, "confirm-approved"):
            media.command(args)

    def test_carousel_package_writes_private_renderable_assets(self) -> None:
        plan = media.validate_plan(
            {
                "media_type": "CAROUSEL_PDF",
                "rationale": "The post contains a practical sequence worth saving.",
                "reader_job": "Use the sequence in a review.",
                "headline": "Before your agent ships",
                "visual_direction": "Simple square cards with one decision per panel.",
                "image_prompt": "",
                "slides": [
                    "Set the spending boundary.",
                    "Test what happens at the limit.",
                    "Measure cost per successful task.",
                    "Decide who can restart spending.",
                ],
                "video_beats": [],
                "alt_text": "Four checks for an agent spending review.",
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "media"
            media.write_package(
                plan,
                post="Approved post text.",
                topic="Agent budgets",
                output_dir=target,
            )
            self.assertTrue((target / "media-plan.json").is_file())
            self.assertTrue((target / "carousel.md").is_file())
            self.assertTrue((target / "carousel.html").is_file())
            self.assertIn("1080px", (target / "carousel.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
