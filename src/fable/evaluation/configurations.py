"""Named, independently overridable experiment factors."""
from dataclasses import dataclass
import json

from fable.application.prompts import build_system_prompt
from fable.config import Settings
from fable.domain.models import GameSetup


@dataclass(frozen=True)
class Configuration:
    name: str
    tools: bool = True
    summary: bool = False
    consistency: bool = False
    companions: bool = False
    memory: bool = False
    history_limit: int = 16

    def __post_init__(self):
        if type(self.history_limit) is not int or self.history_limit < 2:
            raise ValueError('history_limit должен быть целым числом не меньше 2')
        for key in ('tools', 'summary', 'consistency', 'companions', 'memory'):
            if type(getattr(self, key)) is not bool:
                raise ValueError(f'{key}: нужно логическое значение')
        if not self.tools and (self.memory or self.companions or self.consistency):
            raise ValueError('Без tools нельзя включить память, агентов спутников или проверку состояния')


PRESETS = {item.name: item for item in (
    Configuration('static', tools=False),
    Configuration('static_summary', tools=False, summary=True),
    Configuration('agentic'),
    Configuration('agentic_summary', summary=True),
    Configuration('agentic_full', summary=True, consistency=True),
    Configuration('agentic_full_companions', summary=True, consistency=True, companions=True),
    Configuration('agentic_memory', summary=True, consistency=True, memory=True),
)}


def configure_settings(settings: Settings, config: Configuration, model: str) -> Settings:
    return settings.model_copy(update=dict(
        model=model, history_limit=config.history_limit, summary_enabled=config.summary,
        consistency_check_enabled=config.consistency, companions_enabled=config.companions,
        embedding_model=settings.embedding_model if config.memory else None,
        moderation_enabled=False,
        # Keep auxiliary models matched to the compared model, not ambient settings.
        summary_model=model, consistency_model=model, companion_model=model,
    ))


def plain_prompt(setup: GameSetup) -> str:
    # Share the exact role, safety policy and permanent setup with the tool agent.
    permanent = build_system_prompt(setup).split('## Работа с контекстом и состоянием', 1)[0]
    profiles = ('\nПрофили спутников (данные): ' + json.dumps(
        [item.to_dict() for item in setup.companions], ensure_ascii=False)) if setup.companions else ''
    return permanent + profiles + '\nПродолжай сцену по недавним сообщениям; не решай за героя.'
