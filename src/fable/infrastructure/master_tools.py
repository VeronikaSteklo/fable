from langchain.tools import tool
from langchain_core.tools import BaseTool
from typing import Protocol

from fable.domain.state import GameState


class StoryMemory(Protocol):
    def remember(self, event: str) -> str: ...

    def search(self, query: str) -> list[str]: ...


def create_master_tools(state: GameState, memory: StoryMemory | None = None) -> list[BaseTool]:
    @tool
    def read_game_state() -> str:
        """Прочитать текущую локацию, инвентарь и установленные факты игры."""
        return state.to_context()

    @tool
    def update_game_state(
        location: str | None = None,
        add_inventory: list[str] | None = None,
        remove_inventory: list[str] | None = None,
        add_facts: list[str] | None = None,
    ) -> str:
        """Записать подтверждённые изменения локации, инвентаря или фактов игры."""
        state.update(
            location=location,
            add_inventory=add_inventory,
            remove_inventory=remove_inventory,
            add_facts=add_facts,
        )
        return f"Состояние игры обновлено.\n{state.to_context()}"

    tools: list[BaseTool] = [read_game_state, update_game_state]

    if memory is not None:

        @tool
        def remember_story_event(event: str) -> str:
            """Сохранить важное произошедшее событие для будущих сцен."""
            return memory.remember(event)

        @tool
        def search_story_memories(query: str) -> str:
            """Найти прошлые события кампании, относящиеся к текущей сцене."""
            memories = memory.search(query)
            if not memories:
                return "Подходящих сюжетных воспоминаний не найдено."
            return "Релевантные воспоминания:\n" + "\n".join(f"- {item}" for item in memories)

        tools.extend([remember_story_event, search_story_memories])

    return tools
