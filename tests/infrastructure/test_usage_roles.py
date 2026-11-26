"""Exercise real adapters with SDK-shaped offline responses, including tool rounds."""
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from fable.application.game.session import GameSession
from fable.domain.game.state import GameState
from fable.evaluation.scenarios import load_scenarios
from fable.infrastructure.agents.master import GameMasterAgent
from fable.infrastructure.agents.companion import LLMCompanionVoice
from fable.infrastructure.checks.consistency import LLMConsistencyChecker
from fable.infrastructure.checks.moderator import LLMModerator
from fable.infrastructure.checks.summarizer import LLMSummarizer
from fable.infrastructure.llm.client import ChatModel
from tests.infrastructure.agents.test_master_agent import FakeClient, call, chunk, settings


def usage():
    return NS(prompt_tokens=8, completion_tokens=2, total_tokens=10)


def model(text):
    def create(**kwargs):
        return NS(choices=[NS(message=NS(content=text))], usage=usage())
    return ChatModel(NS(chat=NS(completions=NS(create=create))), 'test')


class AdapterUsageTests(unittest.TestCase):
    def test_all_real_roles_share_turn_and_master_tool_rounds_count(self):
        setup = next(s.setup for s in load_scenarios(Path('eval/scenarios')) if s.setup.companions)
        name = setup.companions[0].name
        state = GameState.for_setup(setup)
        client = FakeClient(
            [chunk(calls=[call(name='ask_companion', args='{"name":"' + name + '","situation":"Рядом"}', id='voice')]), NS(choices=[], usage=usage())],
            [chunk('Сцена'), NS(choices=[], usage=usage())],
            [chunk('Вторая'), NS(choices=[], usage=usage())],
            [chunk('Третья'), NS(choices=[], usage=usage())],
        )
        voice = LLMCompanionVoice(model('Я рядом.'), setup)
        with patch('fable.infrastructure.agents.master.build_client', return_value=client):
            master = GameMasterAgent(settings(), 'Роль', state, setup=setup, companion_voice=voice)
        session = GameSession(master, 2, LLMModerator(model('{"allowed":true,"category":null,"reason":""}')),
                              checker=LLMConsistencyChecker(model('{"consistent":true,"issues":[]}')),
                              summarizer=LLMSummarizer(model('Сводка')))
        session.start()
        first = session.last_usage
        self.assertEqual(first['llm_calls'], 4)
        self.assertEqual(first['by_role']['master']['calls'], 2)
        self.assertEqual(first['by_role']['companion']['calls'], 1)
        self.assertEqual(first['by_role']['consistency']['calls'], 1)
        self.assertFalse(first['estimated'])
        session.send_action('Жду')
        session.send_action('Иду')
        last = session.last_usage
        self.assertEqual(last['llm_calls'], 4)
        self.assertEqual(set(last['by_role']), {'master', 'moderator', 'consistency', 'summarizer'})
        self.assertEqual(last['total_tokens'], 40)
        self.assertEqual(session.usage_total['llm_calls'], 11)
