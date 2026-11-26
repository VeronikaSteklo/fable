"""Wire schemas; domain verdicts and legacy text parsers stay separate."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from fable.domain.safety import RiskCategory


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
