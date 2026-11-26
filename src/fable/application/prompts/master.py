"""Master role and permanent campaign context, independent of any LLM adapter."""
import json

from fable.domain.game.setup import GameSetup
from fable.application.prompts.loader import load_prompt, render_prompt

SYSTEM_PROMPT = load_prompt('master_system')
SAFETY_POLICY = load_prompt('safety_policy')


def build_permanent_prompt(setup: GameSetup) -> str:
    character = setup.character
    return render_prompt(
        'master_setup', system=SYSTEM_PROMPT, safety=SAFETY_POLICY,
        world=setup.world, story=setup.story, genre=character.genre,
        name=character.name, role=character.role, goal=character.goal,
        description=character.description or 'не указано',
    )


def build_system_prompt(setup: GameSetup, vector_memory_enabled: bool = False,
                        *, companions_enabled: bool = True) -> str:
    memory = load_prompt('master_memory_enabled' if vector_memory_enabled else 'master_memory_disabled')
    return build_permanent_prompt(setup) + render_prompt(
        'master_context_rules', memory=memory,
        companions=_companion_instructions(setup, companions_enabled),
    )


def _companion_instructions(setup: GameSetup, enabled: bool) -> str:
    if not setup.companions:
        return ''
    profiles = json.dumps([item.to_dict() for item in setup.companions], ensure_ascii=False)
    return render_prompt('master_companions', profiles=profiles) + load_prompt(
        'master_companions_enabled' if enabled else 'master_companions_disabled',
    )
