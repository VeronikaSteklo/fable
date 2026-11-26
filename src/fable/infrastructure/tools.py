"""Validated model-facing tools; no orchestration framework required."""
from collections.abc import Callable
from dataclasses import dataclass
import json

from pydantic import BaseModel, ConfigDict


class ToolArguments(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict
    handler: Callable[..., str]
    arguments_model: type[BaseModel]

    @classmethod
    def from_handler(cls, handler: Callable[..., str], arguments: type[BaseModel]) -> 'Tool':
        return cls(handler.__name__, (handler.__doc__ or '').strip(), arguments.model_json_schema(), handler, arguments)

    def to_openai(self) -> dict:
        return {'type': 'function', 'function': {'name': self.name, 'description': self.description,
                                                'parameters': self.parameters}}

    def invoke(self, arguments: dict | str) -> str:
        try:
            data = json.loads(arguments) if isinstance(arguments, str) else arguments
            validated = self.arguments_model.model_validate(data)
            return self.handler(**validated.model_dump())
        except Exception as error:
            return f'Ошибка инструмента «{self.name}»: {error}'
