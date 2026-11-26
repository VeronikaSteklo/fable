"""Strict, human-readable scenario validation; start is turn 0, actions start at 1."""
from dataclasses import dataclass
import json
from pathlib import Path
import re

from fable.domain.game.setup import GameSetup


@dataclass(frozen=True)
class Probe:
    after_turn: int
    fact: str


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    setup: GameSetup
    actions: tuple[str, ...]
    probes: tuple[Probe, ...] = ()

    def to_dict(self) -> dict:
        return dict(id=self.id, title=self.title, setup=self.setup.to_dict(),
                    actions=list(self.actions), probes=[vars(p) for p in self.probes])


def _text(value, field: str, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise ValueError(f'{field}: нужна непустая строка')
    return value


def parse_scenario(data: dict) -> Scenario:
    if not isinstance(data, dict):
        raise ValueError('Сценарий должен быть JSON-объектом')
    identifier = _text(data.get('id'), 'id')
    if not re.fullmatch(r'[a-zA-Z0-9_-]+', identifier):
        raise ValueError('id: допустимы латинские буквы, цифры, _ и -')
    title = _text(data.get('title'), 'title')
    setup = data.get('setup')
    if not isinstance(setup, dict):
        raise ValueError('setup: нужен объект')
    for key in ('world', 'story'):
        _text(setup.get(key), f'setup.{key}')
    character = setup.get('character')
    if not isinstance(character, dict):
        raise ValueError('setup.character: нужен объект')
    for key in ('name', 'role', 'goal', 'description', 'genre'):
        _text(character.get(key), f'setup.character.{key}', empty=key == 'description')
    companions = setup.get('companions', [])
    if not isinstance(companions, list):
        raise ValueError('setup.companions: нужен массив')
    for index, companion in enumerate(companions):
        if not isinstance(companion, dict):
            raise ValueError(f'setup.companions[{index}]: нужен объект')
        for key in ('name', 'role', 'personality'):
            _text(companion.get(key), f'setup.companions[{index}].{key}')
    parsed_setup = GameSetup.from_dict(setup)
    parsed_setup.validate()
    actions = data.get('actions')
    if not isinstance(actions, list) or not actions:
        raise ValueError('actions: нужен непустой массив действий')
    for index, action in enumerate(actions):
        _text(action, f'actions[{index}]')
    probes = data.get('probes', [])
    if not isinstance(probes, list):
        raise ValueError('probes: нужен массив')
    parsed_probes = []
    for index, probe in enumerate(probes):
        if (not isinstance(probe, dict) or type(probe.get('after_turn')) is not int
                or not 0 <= probe['after_turn'] < len(actions)):
            raise ValueError(f'probes[{index}].after_turn: нужен номер от 0 до {len(actions)-1}')
        parsed_probes.append(Probe(probe['after_turn'], _text(probe.get('fact'), f'probes[{index}].fact')))
    return Scenario(identifier, title, parsed_setup, tuple(actions), tuple(parsed_probes))


def load_scenarios(path: Path) -> list[Scenario]:
    files = sorted(path.glob('*.json')) if path.is_dir() else [path]
    if not files:
        raise ValueError(f'{path}: сценарии *.json не найдены')
    result = []
    seen = set()
    for file in files:
        try:
            scenario = parse_scenario(json.loads(file.read_text(encoding='utf-8')))
            if scenario.id in seen:
                raise ValueError(f'повторный id: {scenario.id}')
            seen.add(scenario.id)
            result.append(scenario)
        except (OSError, ValueError, TypeError, KeyError) as error:
            raise ValueError(f'{file}: {error}') from error
    return result
