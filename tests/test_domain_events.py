import unittest

from fable.domain.companion import Attitude, Companion, CompanionState, InvalidSetupError
from fable.domain.models import Character, GameSetup
from fable.domain.state import GameState


class DomainEventsTests(unittest.TestCase):
    def test_world_events_only_describe_actual_changes_and_are_transient(self):
        state = GameState()
        state.update(location=" Башня ", add_inventory=["Ключ", "ключ"], add_facts=["Дверь открыта", "дверь открыта"])
        events = state.pull_events()
        self.assertEqual([event.type for event in events], ["location_changed", "item_acquired", "fact_established"])
        self.assertEqual(events[0].to_dict(), {"type": "location_changed", "text": "Локация: Башня", "location": "Башня"})
        self.assertTrue(all(event.describe() for event in events))
        from dataclasses import FrozenInstanceError
        with self.assertRaises(FrozenInstanceError):
            setattr(events[0], "location", "Лес")
        self.assertEqual(state.pull_events(), [])
        state.update(location="Башня", add_inventory=["КЛЮЧ"], add_facts=["Дверь открыта"])
        self.assertEqual(state.pull_events(), [])
        state.update(remove_inventory=["КЛЮЧ", "нет"])
        self.assertEqual([event.type for event in state.pull_events()], ["item_lost"])
        self.assertNotIn("events", state.to_dict())
        self.assertEqual(GameState.from_dict(state.to_dict()).pull_events(), [])

    def test_companion_events_and_clamped_noops(self):
        companion = CompanionState("Лис", "Разведчик", notes=["Знаком с героем"])
        state = GameState(companions=[companion])
        self.assertEqual(state.pull_events(), [])
        companion.change_attitude(0)
        companion.remember(" знаком с ГЕРОЕМ ")
        companion.set_present(True)
        self.assertEqual(state.pull_events(), [])
        companion.change_attitude(100)
        companion.remember("Секрет")
        companion.set_present(False)
        companion.set_present(False)
        companion.set_present(True)
        events = state.pull_events()
        self.assertEqual([event.type for event in events], ["companion_attitude_changed", "companion_learned", "companion_left", "companion_returned"])
        self.assertEqual(events[0].to_dict()["delta"], 25)
        self.assertEqual(events[0].to_dict()["companion"], "Лис")
        self.assertEqual(state.pull_events(), [])
        companion.attitude = Attitude(95)
        companion.change_attitude(10)
        event = companion.pull_events()[0]
        self.assertEqual((event.to_dict()["delta"], event.to_dict()["value"]), (5, 100))
        companion.change_attitude(10)
        self.assertEqual(companion.pull_events(), [])
        companion.attitude = Attitude(-100)
        companion.change_attitude(-10)
        self.assertEqual(companion.pull_events(), [])
        self.assertNotIn("events", companion.to_dict())
        self.assertEqual(CompanionState.from_dict(companion.to_dict()).pull_events(), [])

    def test_game_factory_validates_and_initializes_companions(self):
        from fable.domain.game import Game
        setup = GameSetup("мир", "сюжет", Character("Мира", "маг", "найти", "", "фэнтези"),
                          (Companion("Лис", "разведчик", "осторожный"),))
        game = Game.create("one", "owner", setup, "now")
        self.assertEqual((game.id, game.owner_id, game.created_at, game.updated_at), ("one", "owner", "now", "now"))
        self.assertEqual(game.state.companion("лис").role, "разведчик")
        self.assertEqual(game.pull_events(), [])
        invalid = GameSetup(setup.world, setup.story, setup.character, setup.companions * 4)
        with self.assertRaises(InvalidSetupError):
            Game.create("bad", None, invalid, "now")
