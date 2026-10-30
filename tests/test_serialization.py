import json
import unittest

from fable.domain.models import Character, GameSetup
from fable.domain.state import GameState


class SerializationTests(unittest.TestCase):
    def test_setup_and_character_round_trip(self):
        hero = Character("Мира", "Маг", "Спасти город", "В плаще", "Фэнтези")
        setup = GameSetup("Мир", "История", hero)
        data = json.loads(json.dumps(setup.to_dict(), ensure_ascii=False))
        self.assertEqual(GameSetup.from_dict(data), setup)
        self.assertEqual(Character.from_dict(hero.to_dict()), hero)
        self.assertEqual(data["character"]["name"], "Мира")

    def test_game_state_round_trip_does_not_alias_mutable_lists(self):
        state = GameState("Башня", ["Ключ"], ["Страж ушёл"])
        data = state.to_dict()
        restored = GameState.from_dict(data)
        self.assertEqual(restored, state)
        self.assertEqual(GameState.from_dict(GameState().to_dict()), GameState())
        restored.inventory.append("Книга")
        data["facts"].append("Новый факт")
        self.assertEqual(state.inventory, ["Ключ"])
        self.assertEqual(state.facts, ["Страж ушёл"])
        self.assertEqual(restored.facts, ["Страж ушёл"])
