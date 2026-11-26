"""Byte-for-byte prompt snapshots captured from the original package."""
import json
from pathlib import Path
import unittest

from fable.application.prompts import (
    build_companion_prompt, build_start_prompt, build_system_prompt, load_prompt, render_prompt,
)
from fable.bootstrap import create_context_provider
from fable.domain.companions.companion import Companion, CompanionState
from fable.domain.game.setup import GameSetup
from fable.domain.game.state import GameState
from fable.evaluation.configurations import plain_prompt
from fable.infrastructure.checks.summarizer import SUMMARY_PROMPT
from fable.infrastructure.checks.consistency import CONSISTENCY_PROMPT
from fable.infrastructure.checks.moderator import MODERATOR_PROMPT
from fable.infrastructure.checks.judge import JUDGE_RUBRIC, PROBE_RUBRIC


class PromptSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture = next(parent / 'fixtures/prompts_before_refactor.json'
                       for parent in Path(__file__).resolve().parents
                       if (parent / 'fixtures/prompts_before_refactor.json').is_file())
        cls.before = json.loads(fixture.read_text())

    def test_all_templates_render_original_bytes(self):
        for name, case in self.before['templates'].items():
            with self.subTest(template=name):
                self.assertEqual(render_prompt(name, **case['values']).encode(), case['expected'].encode())

    def test_builder_output_matches_before_refactor(self):
        for case in self.before['cases']:
            setup = GameSetup.from_dict(case['setup'])
            for item in case['system']:
                with self.subTest(companions=len(setup.companions), memory=item['memory'], enabled=item['companions']):
                    self.assertEqual(build_system_prompt(setup, item['memory'], companions_enabled=item['companions']).encode(),
                                     item['expected'].encode())
            for item in case['companion']:
                self.assertEqual(build_companion_prompt(setup, Companion.from_dict(item['profile']),
                                                       CompanionState.from_dict(item['state'])).encode(), item['expected'].encode())
            self.assertEqual(plain_prompt(setup).encode(), case['plain'].encode())
            self.assertEqual(create_context_provider(setup, GameState.for_setup(setup))().encode(), case['context'].encode())

    def test_role_constants_and_start_match_original_bytes(self):
        actual = dict(system=load_prompt('master_system'), safety=load_prompt('safety_policy'), start=build_start_prompt(),
                      summary=render_prompt('summary', max_chars=1234), consistency=CONSISTENCY_PROMPT,
                      moderator=MODERATOR_PROMPT, judge=JUDGE_RUBRIC, judge_probe=PROBE_RUBRIC)
        self.assertEqual(actual, self.before['constants'])
        self.assertEqual(SUMMARY_PROMPT, load_prompt('summary'))

    def test_key_instructions_remain(self):
        self.assertIn('не принимать важные решения', load_prompt('master_system'))
        self.assertIn('несовершеннолетних', load_prompt('safety_policy'))
        self.assertIn('информационную асимметрию', load_prompt('companion_system'))
        self.assertIn('не означает recall', load_prompt('judge_probe'))

    def test_tool_descriptions_use_original_templates(self):
        from unittest.mock import Mock
        from fable.infrastructure.agents.master_tools import create_master_tools
        setup = GameSetup.from_dict(self.before['cases'][1]['setup'])
        tools = create_master_tools(GameState.for_setup(setup), Mock(), setup=setup, companion_voice=Mock())
        self.assertEqual(len(tools), 6)
        for tool in tools:
            self.assertEqual(tool.description, self.before['templates']['tool_' + tool.name]['expected'])

    def test_loader_is_cached_and_rejects_paths(self):
        self.assertIs(load_prompt('start'), load_prompt('start'))
        for name in ('../config', '/start', 'start.md', ''):
            with self.subTest(name=name), self.assertRaises(ValueError):
                load_prompt(name)
        with self.assertRaises(FileNotFoundError):
            load_prompt('missing_prompt')
