"""UTF-8 package resources; preserve whitespace and substitute only once."""
from functools import lru_cache
from importlib.resources import files
import re
from string import Template


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    if not re.fullmatch(r'[a-z][a-z0-9_]*', name):
        raise ValueError('Prompt name must be a lowercase resource identifier')
    return files(__package__).joinpath('templates', name + '.md').read_text(encoding='utf-8')


def render_prompt(prompt_name: str, **values: object) -> str:
    return Template(load_prompt(prompt_name)).substitute(values)
