from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Character:
    name: str
    role: str
    goal: str
    description: str
    genre: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Character":
        return cls(**{key: data[key] for key in (
            "name", "role", "goal", "description", "genre"
        )})


@dataclass(frozen=True)
class GameSetup:
    world: str
    story: str
    character: Character

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "GameSetup":
        return cls(world=data["world"], story=data["story"],
                   character=Character.from_dict(data["character"]))
