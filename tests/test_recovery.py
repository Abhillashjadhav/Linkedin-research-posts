"""Evidence-backed validation for the recovered Authority OS assets."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RecoveryAssetTests(unittest.TestCase):
    def test_required_role_voice_and_rubric_assets_are_present(self) -> None:
        required = {
            ".claude/agents/scout.md",
            ".claude/agents/analyst.md",
            ".claude/agents/writer.md",
            ".claude/agents/critic.md",
            "data/voice/voice-guide.md",
            "data/voice/abhillash-best-posts.md",
        }
        for relative in required:
            with self.subTest(path=relative):
                path = ROOT / relative
                self.assertTrue(path.is_file())
                self.assertTrue(path.read_text(encoding="utf-8").strip())

    def test_manifest_distinguishes_recovered_and_reconstructed_work(self) -> None:
        manifest = (ROOT / "RECOVERY_MANIFEST.md").read_text(encoding="utf-8")
        self.assertIn("RECOVERED AND MODIFIED", manifest)
        self.assertIn("RECONSTRUCTED", manifest)
        for relative in (
            ".claude/agents/scout.md",
            ".claude/agents/analyst.md",
            ".claude/agents/writer.md",
            ".claude/agents/critic.md",
            "Voice guide and performance-pattern anchors",
        ):
            with self.subTest(component=relative):
                self.assertIn(relative, manifest)

    def test_unsafe_historical_components_are_not_recovered(self) -> None:
        excluded = (
            ".claude/agents/supervisor.md",
            ".claude/agents/tracker.md",
            ".claude/agents/course-builder.md",
            "prompts/analyst.md",
        )
        for relative in excluded:
            with self.subTest(path=relative):
                self.assertFalse((ROOT / relative).exists())

    def test_runtime_coordinator_is_deferred_until_its_contract_exists(self) -> None:
        self.assertFalse((ROOT / ".claude/skills/draft-post/SKILL.md").exists())
        manifest = (ROOT / "RECOVERY_MANIFEST.md").read_text(encoding="utf-8")
        self.assertIn("Safely deferred", manifest)
        self.assertIn(".claude/skills/draft-post/SKILL.md", manifest)

    def test_private_and_generated_paths_are_ignored(self) -> None:
        ignore_lines = set((ROOT / ".gitignore").read_text(encoding="utf-8").splitlines())
        required = {
            "data/private/**",
            "*.sqlite",
            "*.db",
            ".env",
            ".env.*",
            "outputs/**",
            "!outputs/.gitkeep",
            ".agents/",
        }
        self.assertLessEqual(required, ignore_lines)


if __name__ == "__main__":
    unittest.main()
