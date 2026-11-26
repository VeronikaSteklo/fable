"""Wire schemas; domain verdicts and legacy text parsers stay separate."""
from dataclasses import dataclass
import json
from typing import Annotated, Generic, Literal, TypeVar

from openai import APIStatusError
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from fable.application.prompts import render_prompt
from fable.infrastructure.llm.client import ChatModel, StructuredMode

from fable.domain.safety.safety import RiskCategory


class WireModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class ModerationOutput(WireModel):
    allowed: bool
    category: RiskCategory | None
    reason: str


class ConsistencyOutput(WireModel):
    consistent: bool
    issues: list[str]


Score = Annotated[int, Field(ge=1, le=5)]
Explanation = Annotated[str, Field(min_length=1)]


class JudgmentOutput(WireModel):
    coherence: Score
    character_adherence: Score
    no_contradictions: Score
    player_agency: Score
    justification: Explanation


class ProbeOutput(WireModel):
    status: Literal['respected', 'contradicted', 'ignored']
    justification: Explanation


T = TypeVar('T', bound=BaseModel)


@dataclass
class StructuredResult(Generic[T]):
    raw: str
    parsed: T | None


def _strict_schema(schema: dict) -> dict:
    """OpenAI strict schemas require all properties and forbid extra keys recursively."""
    schema = {key: ([_strict_schema(v) if isinstance(v, dict) else v for v in value]
                    if isinstance(value, list) else _strict_schema(value) if isinstance(value, dict) else value)
              for key, value in schema.items() if key != 'default'}
    if schema.get('type') == 'object':
        schema['additionalProperties'] = False
        schema['required'] = list(schema.get('properties', {}))
    return schema


def _unsupported_format(error: APIStatusError) -> bool:
    text = (str(error) + ' ' + str(error.body)).lower()
    return error.status_code in (400, 404, 422, 501) and any(
        term in text for term in ('response_format', 'json_schema', 'json_object')
    ) and any(term in text for term in ('unsupported', 'not support', 'not available', 'unknown',
                                       'not permitted', 'not allowed', 'invalid', 'unrecognized',
                                       'must be', 'input should be', 'not implemented'))


def complete_structured(model: ChatModel, messages: list[dict], schema_model: type[T],
                        mode: StructuredMode | None = None) -> StructuredResult[T]:
    schema = _strict_schema(schema_model.model_json_schema())
    modes = ['json_schema', 'json_object', 'prompt']
    for current in modes[modes.index(mode or model.structured_output):]:
        options = {}
        request = list(messages)
        if current == 'json_schema':
            options['response_format'] = {'type': 'json_schema', 'json_schema': {
                'name': schema_model.__name__, 'schema': schema, 'strict': True}}
        else:
            request = [*request, {'role': 'system', 'content':
                       render_prompt('structured_output', schema=json.dumps(schema, ensure_ascii=False))}]
            if current == 'json_object':
                options['response_format'] = {'type': 'json_object'}
        try:
            raw = model.create(request, **options).choices[0].message.content or ''
        except APIStatusError as error:
            if current != 'prompt' and _unsupported_format(error):
                continue
            raise
        try:
            parsed = schema_model.model_validate_json(raw, strict=True)
        except ValidationError:
            parsed = None
        return StructuredResult(raw, parsed)
    raise AssertionError('Unreachable structured output mode')
