from fable.application.prompts.loader import load_prompt


def build_start_prompt() -> str:
    return load_prompt('start')
