"""HTTP request bodies; domain setup validation remains in the use case."""
from pydantic import BaseModel, Field, StrictStr


class CharacterBody(BaseModel):
    name: StrictStr
    role: StrictStr
    goal: StrictStr
    description: StrictStr
    genre: StrictStr


class CompanionBody(BaseModel):
    name: StrictStr
    role: StrictStr
    personality: StrictStr


class SetupBody(BaseModel):
    world: StrictStr
    story: StrictStr
    character: CharacterBody
    companions: list[CompanionBody] = Field(default_factory=list)


class ActionBody(BaseModel):
    action: StrictStr
