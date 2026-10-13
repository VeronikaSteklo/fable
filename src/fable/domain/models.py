from dataclasses import dataclass


@dataclass(frozen=True)
class Character:
    name: str
    role: str
    goal: str
    description: str
    genre: str


@dataclass(frozen=True)
class GameSetup:
    world: str
    story: str
    character: Character
