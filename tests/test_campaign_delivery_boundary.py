"""Campaign delivery at the actual model subprocess boundary, without a provider."""
from __future__ import annotations

import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from authority_os import campaign, model_runtime, quality_cli, resonance, workflow
import test_campaign as campaign_fixtures


class CampaignDeliveryBoundaryTests(unittest.TestCase):
    def fixture(self, root: Path) -> tuple[Path, Path, Path, Path]:
        day = campaign_fixtures.CampaignTests().day()
        days = []
        for index, name in enumerate(campaign.EXPECTED_DAYS):
            entry = copy.deepcopy(day)
            entry['day'] = name
            entry['date'] = f'2026-08-{10 + index:02d}'
            days.append(entry)
        spec = root / 'spec.json'
        spec.write_text(json.dumps({'schema_version': 1, 'campaign': 'fixture',
                                    'researched_at': '2026-08-09T00:00:00Z',
                                    'days': days}), encoding='utf-8')
        skill = root / 'SKILL.md'
        evaluation = root / 'eval.md'
        skill.write_text('name: no-ai-slop\nSafe fixture.\n', encoding='utf-8')
        evaluation.write_text('# No AI slop eval\nSafe fixture.\n', encoding='utf-8')
        output = root / 'run'
        for entry in days[1:]:
            folder = output / entry['day'].casefold()
            folder.mkdir(parents=True)
            (folder / 'trace.json').write_text(json.dumps({
                'day': entry['day'], 'final': {'status': 'BLOCKED'},
            }), encoding='utf-8')
        return spec, output, skill, evaluation

    def run_mode(self, mode: str) -> tuple[dict[str, object], Path, list[str]]:
        with tempfile.TemporaryDirectory(dir=workflow.REPO_ROOT) as temporary:
            root = Path(temporary)
            spec, output, skill, evaluation = self.fixture(root)
            called: list[str] = []
            original_run = subprocess.run
            drafts = campaign_fixtures.candidates()
            if mode == 'unsafe_scoreleader':
                drafts[1]['text'] += ' Revenue grew 9876 percent.'

            def provider(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                if command[0] == 'git':
                    return subprocess.CompletedProcess(command, 1, '', '')
                schema = json.loads(Path(command[command.index('--output-schema') + 1]).read_text())
                properties = schema['properties']
                target = Path(command[command.index('--output-last-message') + 1])
                if 'candidates' in properties:
                    stage = 'writer'
                    if mode == 'floor_regression' and called.count('writer') == 1:
                        for item in drafts:
                            item['text'] += ' A product team can use that rule to decide whether to expand.'
                    payload: object = {'candidates': drafts}
                    if mode == 'invalid_writer':
                        payload = {'candidates': [{'id': 'bad', 'text': 'invalid'}]}
                    if mode == 'unsafe_writer':
                        payload = {'candidates': [{**item, 'text': item['text'] + ' Revenue grew 9876 percent.'}
                                                  for item in drafts]}
                elif 'results' in properties:
                    stage = 'narrative'
                    payload = {'results': [
                        {'id': item['id'], 'status': 'UNCHANGED', 'edited_text': item['text'],
                         'claim_ids': item['claim_ids'], 'diagnosis': 'Fixture unchanged.',
                         'repeatable_sentence': 'Set a reliability budget before expanding the workflow.'}
                        for item in drafts
                    ]}
                elif 'scorecards' in properties:
                    stage = 'critic'
                    axes = (5, 5, 5, 5, 3) if mode == 'voice_3' or (mode == 'floor_regression' and called.count('critic') == 0) else \
                           (4, 3, 3, 3, 4) if mode == 'floor_regression' else \
                           (4, 3, 3, 3, 3) if mode == 'later_lower' and called.count('critic') == 0 else \
                           (3, 3, 3, 3, 3) if mode == 'later_lower' else \
                           (4, 4, 4, 4, 4) if mode == 'unsafe_scoreleader' else (5, 5, 5, 5, 5)
                    payload = {'scorecards': [
                        {'candidate_id': item['id'], **dict(zip(workflow.CRITIC_AXES,
                            (5, 5, 5, 5, 5) if mode == 'unsafe_scoreleader' and item['id'] == 'candidate-2' else axes))}
                        for item in drafts
                    ]}
                elif 'edited_text' in properties:
                    stage = 'comment_editor'
                    payload = {'edited_text': 'Unsupported data. https://wrong.example/data',
                               'changes_made': [], 'status': 'PASS', 'failed_checks': []}
                elif 'scores' in properties:
                    stage = 'comment_reviewer'
                    payload = {'scores': {axis: 5 for axis in campaign.COMMENT_AXES}}
                elif 'text' in properties:
                    stage = 'comment_writer'
                    payload = {'text': 'Unsupported data. https://wrong.example/data'}
                elif 'format' in properties:
                    stage = 'artifact'
                    payload = {'format': 'NONE', 'rationale': 'Fixture', 'visual_narrative': 'Fixture', 'panels': []}
                else:
                    raise AssertionError(f'unexpected provider schema: {properties}')
                called.append(stage)
                if mode in {'narrative_invalid_json', 'narrative_array', 'narrative_timeout'} and stage == 'narrative':
                    if mode == 'narrative_timeout':
                        raise subprocess.TimeoutExpired(command, 1)
                    payload = '{invalid' if mode == 'narrative_invalid_json' else []
                if mode in {'critic_invalid_json', 'critic_array', 'critic_timeout'} and stage == 'critic':
                    if mode == 'critic_timeout':
                        raise subprocess.TimeoutExpired(command, 1)
                    payload = '{invalid' if mode == 'critic_invalid_json' else []
                target.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding='utf-8')
                return subprocess.CompletedProcess(command, 0, '', '')

            with patch.object(model_runtime.shutil, 'which', return_value='/fixture/codex'), \
                 patch.object(model_runtime.subprocess, 'run', side_effect=provider):
                summary = campaign.run_campaign(
                    spec_path=spec, output_root=output, no_ai_slop_skill=skill,
                    no_ai_slop_eval=evaluation, only_day='Monday',
                )
            trace = json.loads((output / 'monday' / 'trace.json').read_text())
            post = output / 'monday' / 'post.md'
            retained = output / 'monday' / 'retained-post.md'
            receipt = {
                'summary': summary['execution_outcomes'],
                'final': trace['final'], 'retained': trace.get('retained_post'),
                'post_exists': post.exists(), 'post_mode': post.stat().st_mode & 0o777 if post.exists() else None,
                'retained_mode': retained.stat().st_mode & 0o777 if retained.exists() else None,
                'comment_exists': (output / 'monday' / 'first-comment.md').exists(),
                'trace_mode': (output / 'monday' / 'trace.json').stat().st_mode & 0o777,
            }
            return receipt, output, called

    def test_first_optional_stage_failures_keep_unscored_grounded_post(self) -> None:
        for mode in ('narrative_invalid_json', 'narrative_array', 'narrative_timeout',
                     'critic_invalid_json', 'critic_array', 'critic_timeout'):
            with self.subTest(mode=mode):
                receipt, _output, called = self.run_mode(mode)
                self.assertEqual(receipt['final']['status'], 'COMPLETED_WITH_WARNINGS')
                self.assertTrue(receipt['post_exists'])
                self.assertIsNone(receipt['retained']['score'])
                self.assertIn('critic_not_evaluated', receipt['final']['warnings'])
                self.assertEqual(receipt['post_mode'], 0o600)
                self.assertEqual(receipt['retained_mode'], 0o600)
                self.assertEqual(receipt['trace_mode'], 0o600)
                self.assertEqual(called.count('writer'), 1)

    def test_voice_three_scores_deliver_after_bounded_cycles(self) -> None:
        receipt, _output, called = self.run_mode('voice_3')
        self.assertEqual(receipt['final']['status'], 'COMPLETED_WITH_WARNINGS')
        self.assertEqual(receipt['retained']['score']['effective_total'], 23)
        self.assertIn('voice_fidelity', receipt['final']['warnings'])
        self.assertEqual(called.count('writer'), campaign.MAX_CANDIDATE_CYCLES)
        self.assertEqual(called.count('critic'), campaign.MAX_CANDIDATE_CYCLES)
        self.assertFalse(receipt['comment_exists'])

    def test_later_lower_score_cannot_replace_first_safe_scored_post(self) -> None:
        receipt, _output, called = self.run_mode('later_lower')
        self.assertEqual(receipt['final']['status'], 'COMPLETED_WITH_WARNINGS')
        self.assertEqual(receipt['retained']['score']['effective_total'], 16)
        self.assertEqual(called.count('critic'), campaign.MAX_CANDIDATE_CYCLES)

    def test_unsupported_high_score_cannot_replace_grounded_post(self) -> None:
        receipt, _output, called = self.run_mode('unsafe_scoreleader')
        self.assertEqual(receipt['final']['status'], 'COMPLETED_WITH_WARNINGS')
        self.assertNotEqual(receipt['retained']['candidate_id'], 'candidate-2')
        self.assertNotIn('9876', receipt['retained']['text'])
        self.assertTrue(receipt['post_exists'])

    def test_later_floor_pass_cannot_replace_stronger_grounded_draft(self) -> None:
        receipt, _output, called = self.run_mode('floor_regression')
        self.assertEqual(receipt['final']['status'], 'COMPLETED_WITH_WARNINGS')
        self.assertEqual(receipt['retained']['score']['effective_total'], 23)
        self.assertNotIn('A product team can use that rule', receipt['retained']['text'])
        self.assertEqual(receipt['final']['post'], receipt['retained']['text'])
        self.assertIn('voice_fidelity', receipt['final']['warnings'])
        self.assertEqual(called.count('critic'), 2)

    def test_unsafe_comment_never_becomes_ready_or_erases_post(self) -> None:
        receipt, _output, called = self.run_mode('unsafe_comment')
        self.assertEqual(receipt['final']['status'], 'COMPLETED_WITH_WARNINGS')
        self.assertTrue(receipt['post_exists'])
        self.assertFalse(receipt['comment_exists'])
        self.assertEqual(called.count('comment_reviewer'), 2)

    def test_invalid_and_unsupported_writer_never_create_post(self) -> None:
        for mode in ('invalid_writer', 'unsafe_writer'):
            with self.subTest(mode=mode):
                receipt, _output, called = self.run_mode(mode)
                self.assertEqual(receipt['final']['status'], 'BLOCKED')
                self.assertFalse(receipt['post_exists'])
                self.assertIsNone(receipt['retained'])
                self.assertEqual(called[0], 'writer')
                self.assertNotIn('critic', called)

    def test_campaign_model_egress_requires_explicit_consent(self) -> None:
        args = SimpleNamespace(run_spec=Path('spec.json'), allow_model_egress=False)
        with self.assertRaisesRegex(workflow.WorkflowError, 'allow-model-egress'):
            quality_cli.command_draft(args)

    def test_optional_resonance_parse_failure_does_not_erase_post(self) -> None:
        for invalid in ('{invalid', '[]'):
            with self.subTest(invalid=invalid):
                with tempfile.TemporaryDirectory(dir=workflow.REPO_ROOT) as temporary:
                    root = Path(temporary)
                    day = root / 'monday'
                    day.mkdir(mode=0o700)
                    campaign._private_text(day / 'post.md', 'Grounded draft.\n')
                    campaign._atomic_json(day / 'trace.json', {
                        'day': 'Monday', 'final': {'status': 'READY_FOR_HUMAN_REVIEW',
                                                   'post': 'Grounded draft.'},
                    })
                    campaign._atomic_json(root / 'summary.json', {
                        'days': [{'day': 'Monday', 'status': 'READY_FOR_HUMAN_REVIEW'}],
                    })
                    def provider(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
                        target = Path(command[command.index('--output-last-message') + 1])
                        target.write_text(invalid, encoding='utf-8')
                        return subprocess.CompletedProcess(command, 0, '', '')
                    with patch.object(model_runtime.shutil, 'which', return_value='/fixture/codex'), \
                         patch.object(model_runtime.subprocess, 'run', side_effect=provider):
                        assessments = resonance.apply_post_gate(root, {'Monday': {'status': 'PASS'}})
                    self.assertEqual(assessments['Monday']['status'], 'NOT_EVALUATED')
                    self.assertEqual((day / 'post.md').read_text(), 'Grounded draft.\n')
                    self.assertEqual((day / 'post.md').stat().st_mode & 0o777, 0o600)
                    self.assertEqual((day / 'trace.json').stat().st_mode & 0o777, 0o600)

    def test_secure_checkpoint_failure_never_marks_delivery_complete(self) -> None:
        with tempfile.TemporaryDirectory(dir=workflow.REPO_ROOT) as temporary:
            day = campaign_fixtures.CampaignTests().day()
            trace = campaign._new_trace(day, models=campaign.StageModels.preferred(),
                                        editor_provenance={'repository': 'fixture'},
                                        researched_at='2026-08-09T00:00:00Z')
            original = campaign._private_text
            def fail_checkpoint(path: Path, content: str) -> None:
                if path.name == 'retained-post.md':
                    raise workflow.WorkflowError('Private campaign output could not be written.')
                original(path, content)
            with patch.object(campaign, '_private_text', side_effect=fail_checkpoint):
                with self.assertRaisesRegex(workflow.WorkflowError, 'Private campaign output'):
                    campaign._run_day(day, directory=Path(temporary),
                                      models=campaign.StageModels.preferred(),
                                      invoker=lambda stage, *_: {'candidates': campaign_fixtures.candidates()} if stage == 'writer' else {},
                                      skill='safe', evaluation='safe', editor_provenance={'repository': 'fixture'},
                                      researched_at='2026-08-09T00:00:00Z', trace=trace)
            self.assertNotIn('retained_post', trace)
