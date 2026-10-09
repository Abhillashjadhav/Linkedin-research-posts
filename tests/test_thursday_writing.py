"""Thursday routing reaches live prompts and keeps missing video visible."""
from __future__ import annotations

import json
import tempfile
import unittest
import subprocess
import sys
import os
from pathlib import Path

from authority_os import campaign, media, package, workflow, thursday_capability
import test_campaign
from test_campaign import FakeInvoker
from test_package import fixture_context, write_context


def capability_facts():
    return {
        'creator': 'Example project team', 'capability': 'The project runs a local workflow.',
        'reader_benefit': 'Run representative tasks on local hardware.', 'mechanism': 'The router selects 4 workers.',
        'change_evidence': 'The release adds local execution.', 'limitation': 'Quality varies by task.',
        'conditions': 'The source used 12 GB of memory.', 'demo_observation': 'The original demo shows a generated scene.',
        'attention_evidence': 'No attention counts were verified.', 'original_release_date': '2026-10-07',
        'substantive_change_date': None, 'primary_url': 'https://example.com/project',
        'executable_url': 'https://example.com/download', 'demo_url': 'https://example.com/demo',
        'attention_url': None, 'attention_observed_at': None, 'attention_metric': None,
        'kind': 'EXECUTABLE_CAPABILITY', 'change_kind': 'RELEASE', 'result_provenance': 'SOURCE_REPORTED',
        'attention_count': None,
    }


class ThursdayWritingTests(unittest.TestCase):
    def test_capsule_survives_body_truncation_and_is_bound_to_factual_source(self):
        context = fixture_context()
        fixture = context['fixture']
        items = workflow.prepare_research_items(fixture['research_items'])
        item = next(item for item in items if workflow._theme_for(item['title']) == context['brief']['topic_slug'])
        item['body'] = 'Background. ' * 100 + thursday_capability.CAPSULE_MARKER + json.dumps({
            'policy_version': thursday_capability.POLICY_VERSION, 'evidence': capability_facts()})
        evidence = workflow.build_drafting_evidence([item], topic_slug=context['brief']['topic_slug'])
        self.assertEqual(evidence[0]['thursday_capability']['demo_url'], 'https://example.com/demo')
        self.assertNotIn('4 workers', evidence[0]['claim'])
        self.assertEqual(workflow.candidate_factual_support_diagnostics(
            {'id': 'candidate-1', 'angle': 'mechanism', 'text': 'The router selects 4 workers.', 'claim_ids': ['source-1']}, evidence), [])

    def test_new_metadata_obeys_existing_query_url_privacy_boundary(self):
        evidence = fixture_context()['evidence']
        evidence[0]['thursday_capability'] = capability_facts()
        evidence[0]['thursday_capability']['demo_url'] = 'https://example.com/demo?secret=never-egress'
        evidence[0]['thursday_capability']['conditions'] = 'Read https://example.com/private?secret=embedded-token'
        projected = workflow._writer_evidence_projection(evidence)
        self.assertNotIn('never-egress', json.dumps(projected))
        self.assertNotIn('embedded-token', json.dumps(projected))
        self.assertIsNone(projected[0]['thursday_capability']['demo_url'])
        local = workflow._gate_evidence_projection(evidence)
        self.assertIn('never-egress', local[0]['thursday_capability']['demo_url'])

    def test_short_body_capsule_cannot_leak_query_secrets_to_prompt_or_any_export(self):
        context = fixture_context()
        facts = capability_facts()
        facts.update(attention_url='https://example.com/attention?token=private-query-sentinel',
                     attention_observed_at='2026-10-09T00:00:00Z', attention_metric='stars', attention_count=12)
        facts['demo_url'] = 'https://example.com/demo?token=private-demo-sentinel'
        items = workflow.prepare_research_items(context['fixture']['research_items'])
        for item in items:
            item['body'] = 'A new capability.' + thursday_capability.CAPSULE_MARKER + json.dumps({
                'policy_version': thursday_capability.POLICY_VERSION, 'evidence': facts}, sort_keys=True)
        evidence = workflow.build_drafting_evidence(items, topic_slug=context['brief']['topic_slug'])
        self.assertTrue(all(row['claim'] == 'A new capability.' for row in evidence))
        context['evidence'] = evidence
        context['brief']['weekly_slot'] = 3
        prompt = workflow.build_writer_prompt(brief=context['brief'], evidence=evidence, voice_guidance=workflow.load_voice_guidance())
        self.assertNotIn('private-query-sentinel', prompt)
        self.assertNotIn('private-demo-sentinel', prompt)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'output'
            root.mkdir(mode=0o700)
            target = Path(write_context(context, root)['path'])
            for path in target.iterdir():
                self.assertNotIn('private-query-sentinel', path.read_text(), path.name)
                self.assertNotIn('private-demo-sentinel', path.read_text(), path.name)

    def test_grounded_companion_and_shot_plan_are_produced_in_standalone_package(self):
        context = fixture_context()
        context['brief']['weekly_slot'] = 3
        for row in context['evidence']:
            row['thursday_capability'] = capability_facts()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'output'
            root.mkdir(mode=0o700)
            result = write_context(context, root)
            target = Path(result['path'])
            comment = (target / 'source-comment.md').read_text()
            final = (target / 'final-package.md').read_text()
            evaluation = json.loads((target / 'evaluation.json').read_text())
            self.assertIn('The router selects 4 workers.', comment)
            self.assertIn('12 GB', comment)
            self.assertIn('https://example.com/demo', comment)
            self.assertIn('correctness', comment)
            self.assertIn('15–55 seconds: one diagram', final)
            self.assertIn('PLAN_ONLY', final)
            self.assertEqual(evaluation['thursday_package']['first_comment'], 'GROUNDED_COMPANION_DRAFT_REVIEW_REQUIRED')

    def test_installed_launcher_overlays_preserve_thursday_and_ordinary_routes(self):
        launcher = (workflow.REPO_ROOT / 'bin' / 'linkedin-os').read_text()
        stack = launcher.split("import sys\n", 1)[1].split('from authority_os import standalone_draft_observability', 1)[0]
        probe = '''
from test_package import fixture_context
from authority_os import workflow
voice = workflow.load_voice_guidance()
b = dict(c['brief'], weekly_slot=3)
p = workflow.build_writer_prompt(brief=b, evidence=c['evidence'], voice_guidance=voice)
assert 'THURSDAY CAPABILITY WRITING' in p
assert 'SOCIAL_MEDIA_HUMAN_REVIEW_POLICY' not in p
q = workflow.build_writer_prompt(brief=dict(c['brief'], weekly_slot=2), evidence=c['evidence'], voice_guidance=voice)
assert 'THURSDAY CAPABILITY WRITING' not in q
assert 'SOCIAL_MEDIA_HUMAN_REVIEW_POLICY' in q
r = workflow.build_critic_prompt(c['review']['candidates'], b, c['evidence'])
assert 'THURSDAY' in r
'''
        env = dict(os.environ, PYTHONPATH=str(workflow.REPO_ROOT / 'src') + os.pathsep + str(workflow.REPO_ROOT / 'tests'))
        completed = subprocess.run([sys.executable, '-c', 'import sys\nfrom test_package import fixture_context\nc = fixture_context()\n' + stack + probe], env=env, text=True, capture_output=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
    def test_weekly_slot_routes_writer_critic_and_revision_without_wednesday_leak(self):
        context = fixture_context()
        brief = dict(context['brief'], weekly_slot=3)
        evidence = context['evidence']
        voice = workflow.load_voice_guidance()
        writer = workflow.build_writer_prompt(brief=brief, evidence=evidence, voice_guidance=voice)
        self.assertIn('THURSDAY', writer.upper())
        critic = workflow.build_critic_prompt(context['review']['candidates'], brief, evidence)
        self.assertIn('THURSDAY', critic.upper())
        revision = workflow._build_writer_revision_prompt(
            candidate=context['review']['candidates'][0], scorecard=context['review']['scorecards'][0],
            brief=brief, evidence=evidence, voice_guidance=voice)
        self.assertIn('THURSDAY', revision.upper())
        wednesday = dict(context['brief'], weekly_slot=2)
        self.assertNotIn('THURSDAY', workflow.build_writer_prompt(
            brief=wednesday, evidence=evidence, voice_guidance=voice).upper())

    def test_campaign_day_is_not_inferred_from_fourth_weekly_slot(self):
        day = test_campaign.CampaignTests().day()
        day['day'] = 'Thursday'
        self.assertEqual(workflow._writer_brief_projection(campaign._brief(day))['day'], 'Thursday')
        day['day'] = 'Wednesday'
        self.assertNotIn('day', workflow._writer_brief_projection(campaign._brief(day)))
        self.assertTrue(campaign._artifact_policy_passes('Thursday', 'VIDEO_PLAN'))
        self.assertFalse(campaign._artifact_policy_passes('Thursday', 'DIAGRAM'))
        self.assertTrue(campaign._artifact_policy_passes('Wednesday', 'DIAGRAM'))

    def test_comment_cannot_promise_original_demo_then_link_only_repository(self):
        day = {'day': 'Thursday'}
        evidence = [
            {'source': 'https://example.com/project', 'title': 'Project repository', 'claim': 'The README links to an original demo.', 'thursday_capability': capability_facts()},
            {'source': 'https://example.com/demo', 'title': 'Original demo', 'claim': 'The video shows the actual output.'},
        ]
        post = 'Project and original demo in the first comment.'
        failed = campaign._comment_evidence_gates(
            {'text': 'Project: https://example.com/project'}, post_text=post, evidence=evidence, day=day)
        self.assertFalse(failed['passes'])
        self.assertEqual(failed['promised_demo_link'], 'FAIL')
        passed = campaign._comment_evidence_gates(
            {'text': 'Project: https://example.com/project Demo: https://example.com/demo'},
            post_text=post, evidence=evidence, day=day)
        self.assertTrue(passed['passes'])

    def test_campaign_keeps_post_comment_and_handoff_without_claiming_finished_mp4(self):
        seen = {}
        class ThursdayInvoker(FakeInvoker):
            def __call__(self, stage, config, role, task, schema):
                seen[stage] = task
                if stage == 'artifact_editor':
                    self.calls.append(stage)
                    return {'format': 'VIDEO_PLAN', 'rationale': 'Show a real demonstration.',
                            'visual_narrative': 'Actual output then a camera moving over one diagram. Footage needed.',
                            'panels': [{'heading': heading, 'body': 'Show the supplied source evidence.', 'claim_ids': ['source-1']}
                                       for heading in ['Actual output', 'Mechanism diagram', 'Limit and test']]}
                if stage == 'visual_qa':
                    raise AssertionError('Unrendered video cannot pass visual QA')
                return super().__call__(stage, config, role, task, schema)
        day = test_campaign.CampaignTests().day()
        day['day'] = 'Thursday'
        invoker = ThursdayInvoker()
        with tempfile.TemporaryDirectory(dir=workflow.REPO_ROOT) as temporary:
            target = Path(temporary)
            trace = campaign._run_day(day, directory=target, models=campaign.StageModels.preferred(),
                invoker=invoker, skill='Minimum edit.', evaluation='Pass or fail.',
                editor_provenance={}, researched_at='2026-08-09T00:00:00Z')
            campaign._persist_day(target, trace)
            self.assertEqual(trace['final']['status'], 'COMPLETED_WITH_WARNINGS')
            self.assertFalse(trace['final']['full_package_complete'])
            self.assertEqual(trace['artifact']['status'], 'PLAN_ONLY')
            self.assertEqual(trace['visual_qa']['overall'], 'NOT_EVALUATED')
            for name in ['post.md', 'first-comment.md', 'video-production-handoff.md']:
                self.assertTrue((target / name).is_file(), name)
            self.assertFalse(list(target.glob('*.svg')))
            self.assertFalse(list(target.glob('*.mp4')))
        for stage in ['writer', 'narrative_editor', 'critic', 'first_comment_writer',
                      'first_comment_reviewer', 'first_comment_no_ai_slop', 'artifact_editor']:
            self.assertIn('THURSDAY', seen[stage].upper(), stage)
        self.assertEqual(trace['final']['post'], invoker.drafts[0]['text'])

    def test_source_list_package_is_not_claimed_to_be_full_thursday_package(self):
        context = fixture_context()
        context['brief']['weekly_slot'] = 3
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'output'
            root.mkdir(mode=0o700)
            result = write_context(context, root)
            target = Path(result['path'])
            manifest = json.loads((target / 'manifest.json').read_text())
            self.assertEqual(manifest['thursday_package']['full_package'], 'INCOMPLETE')
            self.assertEqual(manifest['thursday_package']['video'], 'NOT_RENDERED')

    def test_media_day_routes_video_plan_without_rewriting_locked_post(self):
        tasks = []
        def invoker(**kwargs):
            tasks.append(kwargs['task_prompt'])
            return {'media_type': 'VIDEO', 'rationale': 'Demonstrate the output.', 'reader_job': 'Understand the mechanism.',
                    'headline': 'Actual output', 'visual_direction': 'Camera across one diagram.', 'image_prompt': '',
                    'slides': [], 'video_beats': ['Actual output', 'Mechanism diagram', 'Limit and test'], 'alt_text': 'Demo plan.'}
        post = 'User-approved wording stays here.'
        result = media.plan_media(post, 'Capability', day='Thursday', invoker=invoker)
        self.assertEqual(result['media_type'], 'VIDEO')
        self.assertIn(post, tasks[0])
        self.assertIn('THURSDAY', tasks[0].upper())


if __name__ == '__main__':
    unittest.main()
