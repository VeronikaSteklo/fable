import unittest

from fable.domain.state import GameState
from fable.infrastructure.master_tools import create_master_tools


class MasterToolsTests(unittest.TestCase):
    def test_update_and_read_game_state(self) -> None:
        state = GameState()
        tools = {tool.name: tool for tool in create_master_tools(state)}

        result = tools["update_game_state"].invoke(
            {
                "location": "Старая башня",
                "add_inventory": ["Серебряный ключ"],
                "add_facts": ["Дверь запечатана рунами"],
            }
        )
        snapshot = tools["read_game_state"].invoke({})

        self.assertIn("Старая башня", result)
        self.assertIn("Старая башня", snapshot)
        self.assertIn("Серебряный ключ", snapshot)
        self.assertIn("Дверь запечатана рунами", snapshot)
        self.assertEqual(state.location, "Старая башня")

    def test_state_updates_are_idempotent_and_can_remove_items(self) -> None:
        state = GameState()
        tools = {tool.name: tool for tool in create_master_tools(state)}

        tools["update_game_state"].invoke({"add_inventory": ["Ключ"], "add_facts": ["Страж ушёл"]})
        tools["update_game_state"].invoke(
            {
                "add_inventory": ["ключ"],
                "remove_inventory": ["КЛЮЧ"],
                "add_facts": ["страж ушёл"],
            }
        )

        self.assertEqual(state.inventory, [])
        self.assertEqual(state.facts, ["Страж ушёл"])

    def test_memory_tools_are_added_only_when_memory_is_enabled(self) -> None:
        class FakeMemory:
            def __init__(self) -> None:
                self.events: list[str] = []

            def remember(self, event: str) -> str:
                self.events.append(event)
                return "Событие сохранено."

            def search(self, query: str) -> list[str]:
                return [event for event in self.events if query.casefold() in event.casefold()]

        memory = FakeMemory()
        tools = {tool.name: tool for tool in create_master_tools(GameState(), memory)}

        tools["remember_story_event"].invoke({"event": "Мира нашла старый серебряный ключ."})
        result = tools["search_story_memories"].invoke({"query": "серебряный ключ"})

        self.assertIn("Мира нашла старый серебряный ключ", result)
        self.assertNotIn(
            "search_story_memories",
            {tool.name for tool in create_master_tools(GameState())},
        )


if __name__ == "__main__":
    unittest.main()
