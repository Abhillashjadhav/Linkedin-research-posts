"""Offline checks for the composed Monday Reach discovery-to-text-draft route."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class MondayDiscoveryRouteTests(unittest.TestCase):
    def _probe(self, script: str) -> dict[str, object]:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        completed = subprocess.run(
            [sys.executable, "-c", script], cwd=ROOT, env=env,
            capture_output=True, text=True, check=True,
        )
        return json.loads(completed.stdout.splitlines()[-1])

    def test_actual_composed_command_agrees_with_printed_monday_draft(self) -> None:
        result = self._probe(r'''
import io, json, shlex, tempfile
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest.mock import patch
from authority_os import daily_discovery_cli as live, daily_spine_cli as spine, topic_value, workflow
from tests.test_daily_spine_cli import profile, signals, value_candidates, cards

as_of = '2026-10-05T09:04:06Z'
workflow.DEFAULT_PRIVATE_DATA.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(dir=workflow.DEFAULT_PRIVATE_DATA) as temporary, ExitStack() as stack:
    root = Path(temporary)
    output = root / 'run'
    profile_path = root / 'profile.json'
    raw_profile = profile()
    raw_profile['proof_inventory'] = []
    profile_path.write_text(json.dumps(raw_profile), encoding='utf-8')
    profile_path.chmod(0o600)
    topic = {'id': 'topic-1', 'topic': 'Agent reliability', 'total': 20,
             'observed_axes': 5, 'authority_fit': {'total': 22},
             'representative_urls': ['https://example.com/1']}
    resume = spine.DiscoveryResume(root / 'previous', as_of, (topic,), (topic,), 'momentum-qualified', ())
    stack.enter_context(patch.object(spine, 'load_discovery_resume', return_value=resume))
    stack.enter_context(patch.object(spine, 'resolve_signal_evidence', return_value=
        spine.EvidenceResolution(tuple(signals()), 'fixture', 0, 'fixture')))
    stack.enter_context(patch.object(spine.base, 'project_signals', return_value=signals()))
    stack.enter_context(patch.object(spine.base.legacy_cli, 'initialise_paths'))
    stack.enter_context(patch.object(spine.storage, 'insert_research_items', return_value=(3, 0)))
    stack.enter_context(patch.object(topic_value, 'invoke_discovery_selector', return_value=value_candidates()))
    stack.enter_context(patch.object(topic_value, 'project_discovery_signals', return_value=signals()))
    stack.enter_context(patch.object(spine, 'generate_cards', return_value=[
        {**card, 'proof_id': 'NOT_REQUIRED'} for card in cards()
    ]))
    stack.enter_context(patch.object(spine.base, 'score_cards', return_value=[
        {'thesis_id': f'thesis-{i}', **{axis: 4 for axis in spine.base.AXES}, 'total': 20}
        for i in range(1, 4)
    ]))
    stack.enter_context(patch.object(spine.v1_completion, '_read_jsonl', return_value=[]))
    stack.enter_context(patch.object(workflow, 'load_voice_guidance', return_value={}))
    stack.enter_context(patch.object(spine.eval_dashboard_html, 'open_dashboard', return_value=False))
    child = stack.enter_context(patch.object(spine, 'run_drafting_child', return_value=
        spine.DraftingRun(0, 'completed', 'fixture.log', ())))
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        status = live.main([
            '--profile', str(profile_path), '--resume-from', str(resume.source_folder),
            '--output-dir', str(output), '--db', str(root / 'db.sqlite'),
            '--week-slot', '1', '--allow-web-research', '--allow-model-egress', '--generate-post',
        ])
    commands = [line.removeprefix('Draft command: ') for line in stdout.getvalue().splitlines()
                if line.startswith('Draft command: ')]
    printed = shlex.split(commands[0])
    argv = child.call_args.args[0]
    identity = json.loads((output / 'run-input.json').read_text())
    package = json.loads((output / 'theses.json').read_text())
    dashboard = json.loads((output / 'run-dashboard.json').read_text())
    print(json.dumps({
        'status': status, 'printed_tail': printed[1:], 'child_tail': argv[1:],
        'printed_executable': printed[0], 'child_executable': argv[0],
        'as_of': identity['as_of'], 'child_as_of': child.call_args.kwargs['env']['LINKEDIN_OS_DRAFT_AS_OF'],
        'goal': identity['strategic_goal'], 'package_goal': package['strategic_goal'],
        'dashboard_goal': dashboard['strategic_goal'], 'slot': identity['weekly_slot'],
        'package_slot': package['weekly_slot'], 'outcome': dashboard['outcome'],
    }))
''')
        self.assertEqual(result["status"], 0)
        self.assertEqual(result["printed_tail"], result["child_tail"])
        self.assertEqual(result["printed_executable"], "./bin/linkedin-os")
        self.assertEqual(result["child_executable"], str(ROOT / "bin" / "linkedin-os"))
        tail = result["child_tail"]
        self.assertEqual(tail[tail.index("--goal") + 1], "reach")
        self.assertEqual(tail[tail.index("--format") + 1], "text")
        self.assertEqual(tail[tail.index("--week-slot") + 1], "1")
        self.assertEqual(result["as_of"], "2026-10-05T09:04:06Z")
        self.assertEqual(result["child_as_of"], result["as_of"])
        self.assertEqual(result["goal"], result["package_goal"])
        self.assertEqual(result["goal"], result["dashboard_goal"])
        self.assertEqual(result["slot"], result["package_slot"])
        self.assertEqual(result["outcome"], "PASS")

    def test_omitted_as_of_is_actual_utc_invocation_time(self) -> None:
        result = self._probe(r'''
import json, tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from authority_os import daily_discovery_cli as live

live.base.workflow.DEFAULT_PRIVATE_DATA.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(dir=live.base.workflow.DEFAULT_PRIVATE_DATA) as temporary:
    args = live.parser().parse_args(['--profile', 'data/private/unused.json', '--week-slot', '1',
                                      '--output-dir', str(Path(temporary) / 'run')])
    observed = []
    before = datetime.now(timezone.utc)
    with patch.object(live.momentum_surface_parallel, 'configure_trace_dir'), patch.object(
        live.base.base.legacy_cli, '_ensure_owner_only_directory'
    ), patch.object(live, '_ORIGINAL_COMMAND', side_effect=lambda parsed: observed.append(parsed.as_of) or 0), patch.object(
        live, '_delivered', return_value=True
    ):
        live.command(args)
    after = datetime.now(timezone.utc)
print(json.dumps({'before': before.isoformat(), 'after': after.isoformat(), 'as_of': observed[0]}))
''')
        from datetime import datetime

        self.assertLessEqual(datetime.fromisoformat(result["before"]).replace(microsecond=0), datetime.fromisoformat(result["as_of"].replace("Z", "+00:00")))
        self.assertLessEqual(datetime.fromisoformat(result["as_of"].replace("Z", "+00:00")), datetime.fromisoformat(result["after"]))


if __name__ == "__main__":
    unittest.main()
