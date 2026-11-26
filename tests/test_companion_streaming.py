import json
import unittest
from unittest.mock import patch

from fable.domain.companion import Companion
from fable.domain.state import GameState
from fable.infrastructure.companion_agent import LLMCompanionVoice
from fable.infrastructure.master_agent import GameMasterAgent
from test_companions import setup_with
from test_llm_summarizer import FakeModel
from test_master_agent import FakeClient, chunk, call, settings


class CompanionStreamingTests(unittest.TestCase):
    def test_real_loop_orchestrates_companion_and_keeps_tool_metadata_private(self):
        setup = setup_with(Companion('Лис', 'Разведчик', 'Осторожный'))
        state = GameState.for_setup(setup)
        client = FakeClient([
            chunk(calls=[call(name='ask_companion', args=json.dumps({
                'name': 'Лис', 'situation': 'Мира вытащила Лиса с горящего моста'}), id='ask')], finish='tool_calls'),
        ], [
            chunk(calls=[call(name='update_companion', args=json.dumps({
                'name': 'Лис', 'attitude_change': 20, 'note': 'Мира спасла Лиса'}), id='update')], finish='tool_calls'),
        ], [chunk('Лис говорит: «Бежим!»', finish='stop')])
        voice = FakeModel('«Бежим!»')
        with patch('fable.infrastructure.master_agent.build_client', return_value=client):
            master = GameMasterAgent(settings(), 'Промпт', state, setup=setup,
                                     companion_voice=LLMCompanionVoice(voice, setup))
        self.assertEqual(list(master.stream([{'role': 'user', 'content': 'Спасаю Лиса'}])), ['Лис говорит: «Бежим!»'])
        results = [m for m in client.requests[-1]['messages'] if m['role'] == 'tool']
        self.assertEqual([m['tool_call_id'] for m in results], ['ask', 'update'])
        self.assertEqual(results[0]['content'], '«Бежим!»')
        self.assertEqual(state.companion('Лис').attitude.value, 20)
        self.assertEqual(state.companion('Лис').notes, ['Мира спасла Лиса'])
        self.assertEqual(len(voice.requests), 1)

    def test_only_assistant_content_reaches_scene(self):
        state = GameState(location='Секретная башня')
        client = FakeClient([chunk(calls=[call(name='read_game_state', args='{}', id='read')], finish='tool_calls')],
                            [chunk('Сцена', finish='stop')])
        with patch('fable.infrastructure.master_agent.build_client', return_value=client):
            master = GameMasterAgent(settings(), 'Промпт', state)
        self.assertEqual(list(master.stream([])), ['Сцена'])
        self.assertIn('Секретная башня', client.requests[-1]['messages'][-1]['content'])
