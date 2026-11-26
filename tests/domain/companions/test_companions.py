import unittest

from fable.domain.game.setup import Character, GameSetup
from fable.domain.game.state import GameState
from fable.domain.companions.companion import Attitude, Companion, CompanionState, InvalidSetupError


def setup_with(*companions):
    return GameSetup("Мир", "История", Character("Мира", "Маг", "Цель", "", "Фэнтези"), companions)


class CompanionDomainTests(unittest.TestCase):
    def test_attitude_boundaries_and_change_limits(self):
        for value, label in [(-101, "враждебно"), (-60, "враждебно"), (-59, "настороженно"),
                             (-20, "настороженно"), (-19, "нейтрально"), (19, "нейтрально"),
                             (20, "дружелюбно"), (59, "дружелюбно"), (60, "доверяет"), (101, "доверяет")]:
            with self.subTest(value=value):
                self.assertEqual(Attitude(value).label, label)
                self.assertLessEqual(abs(Attitude(value).value), 100)
        self.assertEqual(Attitude(-101).value, -100)
        self.assertEqual(Attitude(101).value, 100)
        self.assertEqual(Attitude(-90).changed(-20).value, -100)
        original = Attitude(90)
        self.assertEqual(original.changed(20).value, 100)
        self.assertEqual(original.value, 90)
        state = CompanionState("Лис", "Разведчик")
        state.change_attitude(1000)
        self.assertEqual(state.attitude.value, 25)
        state.change_attitude(-1000)
        self.assertEqual(state.attitude.value, 0)

    def test_notes_dedupe_and_keep_twenty_newest(self):
        state = CompanionState("Лис", "Разведчик")
        for note in [" Тайна ", "тайна", " "]:
            state.remember(note)
        self.assertEqual(state.notes, ["Тайна"])
        for i in range(25):
            state.remember(str(i))
        self.assertEqual(state.notes, [str(i) for i in range(5, 25)])
        state.set_present(False)
        self.assertFalse(state.present)

    def test_round_trip_old_format_and_context(self):
        setup = setup_with(Companion("Лис", "Разведчик", "Осторожный"))
        self.assertEqual(GameSetup.from_dict(setup.to_dict()), setup)
        self.assertIsInstance(setup.to_dict()["companions"], list)
        state = GameState.for_setup(setup)
        companion = state.companion("лИС")
        self.assertIsNotNone(companion)
        companion.change_attitude(20)
        for i in range(7):
            companion.remember(f"Секрет {i}")
        companion.set_present(False)
        data = state.to_dict()
        restored = GameState.from_dict(data)
        self.assertEqual(restored, state)
        self.assertEqual(data["companions"][0]["attitude"], 20)
        self.assertEqual(data["companions"][0]["attitude_label"], "дружелюбно")
        restored.companion("Лис").remember("Новое")
        self.assertNotIn("Новое", companion.notes)
        context = state.to_context()
        for text in ["Спутники:", "Лис", "Разведчик", "дружелюбно", "20", "не рядом", "Секрет 6"]:
            self.assertIn(text, context)
        self.assertNotIn("Секрет 0", context)
        old_setup = setup.to_dict()
        del old_setup["companions"]
        self.assertEqual(GameSetup.from_dict(old_setup).companions, ())
        self.assertEqual(GameState.from_dict({}).companions, [])

    def test_validation(self):
        for companions in [(Companion("", "", ""),), (Companion(" " , "x", ""),),
                           (Companion("x" * 41, "", ""),), (Companion("Лис", "x" * 81, ""),),
                           (Companion("Лис", "", "x" * 1001),), (Companion("мИРА", "", ""),),
                           (Companion("Лис", "", ""), Companion("лИС", "", "")),
                           tuple(Companion(str(i), "", "") for i in range(4))]:
            with self.subTest(companions=companions), self.assertRaises(InvalidSetupError):
                setup_with(*companions).validate()
        setup_with(Companion("Лис", "", "")).validate()
