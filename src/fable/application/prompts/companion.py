"""Personal companion role, including only that companion's private knowledge."""
import json

from fable.domain.companions.companion import Companion, CompanionState
from fable.domain.game.setup import GameSetup
from fable.application.prompts.loader import load_prompt, render_prompt


def build_companion_prompt(setup: GameSetup, profile: Companion, state: CompanionState) -> str:
    data = json.dumps({
        'мир': setup.world[:1500], 'завязка': setup.story[:1500],
        'герой': {'имя': setup.character.name, 'роль': setup.character.role},
        'спутник': profile.to_dict(),
        'отношение к герою': {'метка': state.attitude.label, 'значение': state.attitude.value},
        'личные знания': list(state.notes),
    }, ensure_ascii=False)
    return render_prompt('companion_system', name=json.dumps(profile.name, ensure_ascii=False),
                         safety=load_prompt('safety_policy'), data=data)
