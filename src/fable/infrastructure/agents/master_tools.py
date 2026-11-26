from fable.application.prompts import load_prompt
from fable.application.ports import StoryMemory as StoryMemory
from fable.application.companions.ports import CompanionVoice
from fable.domain.game.setup import GameSetup
from fable.domain.game.state import GameState
from fable.infrastructure.agents.tools import Tool, ToolArguments


class ReadStateArgs(ToolArguments):
    pass


class UpdateStateArgs(ToolArguments):
    location: str | None = None
    add_inventory: list[str] | None = None
    remove_inventory: list[str] | None = None
    add_facts: list[str] | None = None


class AskCompanionArgs(ToolArguments):
    name: str
    situation: str


class UpdateCompanionArgs(ToolArguments):
    name: str
    attitude_change: int = 0
    note: str | None = None
    present: bool | None = None


class RememberArgs(ToolArguments):
    event: str


class SearchArgs(ToolArguments):
    query: str


def create_master_tools(state: GameState, memory: StoryMemory | None = None, *,
                        setup: GameSetup | None = None,
                        companion_voice: CompanionVoice | None = None) -> list[Tool]:
    # Tools translate model calls; only domain methods enforce changes and emit events.
    def read_game_state() -> str:
        return state.to_context()

    def update_game_state(
        location: str | None = None,
        add_inventory: list[str] | None = None,
        remove_inventory: list[str] | None = None,
        add_facts: list[str] | None = None,
    ) -> str:
        state.update(
            location=location,
            add_inventory=add_inventory,
            remove_inventory=remove_inventory,
            add_facts=add_facts,
        )
        return f"Состояние игры обновлено.\n{state.to_context()}"

    read_game_state.__doc__ = load_prompt('tool_read_game_state')
    update_game_state.__doc__ = load_prompt('tool_update_game_state')
    tools: list[Tool] = [Tool.from_handler(read_game_state, ReadStateArgs),
                         Tool.from_handler(update_game_state, UpdateStateArgs)]

    if setup is not None and setup.companions and companion_voice is not None:
        profiles = {item.name.casefold(): item for item in setup.companions}

        def ask_companion(name: str, situation: str) -> str:
            companion = state.companion(name)
            profile = profiles.get(name.strip().casefold())
            if companion is None or profile is None:
                return f"Спутник «{name}» не найден."
            if not companion.present:
                return f"{companion.name} не рядом и не может отреагировать."
            return companion_voice.speak(companion, profile, situation)

        def update_companion(name: str, attitude_change: int = 0, note: str | None = None,
                             present: bool | None = None) -> str:
            companion = state.companion(name)
            if companion is None or name.strip().casefold() not in profiles:
                return f"Спутник «{name}» не найден."
            companion.change_attitude(attitude_change)
            if note is not None:
                companion.remember(note)
            if present is not None:
                companion.set_present(present)
            return companion.to_context()

        ask_companion.__doc__ = load_prompt('tool_ask_companion')
        update_companion.__doc__ = load_prompt('tool_update_companion')
        tools.extend([Tool.from_handler(ask_companion, AskCompanionArgs),
                      Tool.from_handler(update_companion, UpdateCompanionArgs)])

    if memory is not None:

        def remember_story_event(event: str) -> str:
            return memory.remember(event)

        def search_story_memories(query: str) -> str:
            memories = memory.search(query)
            if not memories:
                return "Подходящих сюжетных воспоминаний не найдено."
            return "Релевантные воспоминания:\n" + "\n".join(f"- {item}" for item in memories)

        remember_story_event.__doc__ = load_prompt('tool_remember_story_event')
        search_story_memories.__doc__ = load_prompt('tool_search_story_memories')
        tools.extend([Tool.from_handler(remember_story_event, RememberArgs),
                      Tool.from_handler(search_story_memories, SearchArgs)])

    return tools
