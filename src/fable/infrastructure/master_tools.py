from langchain.tools import tool
from langchain_core.tools import BaseTool

from fable.application.ports import StoryMemory as StoryMemory
from fable.application.companions import CompanionVoice
from fable.domain.models import GameSetup
from fable.domain.state import GameState


def create_master_tools(state: GameState, memory: StoryMemory | None = None, *,
                        setup: GameSetup | None = None,
                        companion_voice: CompanionVoice | None = None) -> list[BaseTool]:
    # Tools translate model calls; only domain methods enforce changes and emit events.
    @tool
    def read_game_state() -> str:
        """Прочитать текущую локацию, инвентарь, факты игры и состояние спутников."""
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

    if setup is not None and setup.companions and companion_voice is not None:
        profiles = {item.name.casefold(): item for item in setup.companions}

        @tool
        def ask_companion(name: str, situation: str) -> str:
            """Получить реакцию присутствующего спутника. Передай только то, что он видит и слышит."""
            companion = state.companion(name)
            profile = profiles.get(name.strip().casefold())
            if companion is None or profile is None:
                return f"Спутник «{name}» не найден."
            if not companion.present:
                return f"{companion.name} не рядом и не может отреагировать."
            return companion_voice.speak(companion, profile, situation)

        @tool
        def update_companion(name: str, attitude_change: int = 0, note: str | None = None,
                             present: bool | None = None) -> str:
            """Записать подтверждённые изменения отношения, знаний или присутствия спутника.

            Отношение меняй небольшими шагами после значимых действий героя.
            Заметка — только то, что спутник действительно узнал; уход требует сюжетной причины.
            """
            companion = state.companion(name)
            if companion is None or name.strip().casefold() not in profiles:
                return f"Спутник «{name}» не найден."
            companion.change_attitude(attitude_change)
            if note is not None:
                companion.remember(note)
            if present is not None:
                companion.set_present(present)
            return companion.to_context()

        tools.extend([ask_companion, update_companion])

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
