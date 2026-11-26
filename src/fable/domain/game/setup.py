from dataclasses import asdict, dataclass

from fable.domain.companions.companion import Companion, InvalidSetupError


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
    companions: tuple[Companion, ...] = ()

    def validate(self) -> None:
        if len(self.companions) > 3:
            raise InvalidSetupError("Можно добавить не более трёх спутников.")
        names = {self.character.name.strip().casefold()}
        for companion in self.companions:
            name = companion.name.strip()
            if not name:
                raise InvalidSetupError("Укажи имя спутника.")
            if len(name) > 40:
                raise InvalidSetupError("Имя спутника должно быть не длиннее 40 символов.")
            if len(companion.role.strip()) > 80:
                raise InvalidSetupError("Роль спутника должна быть не длиннее 80 символов.")
            if len(companion.personality.strip()) > 1000:
                raise InvalidSetupError("Характер спутника должен быть не длиннее 1000 символов.")
            if name.casefold() in names:
                raise InvalidSetupError("Имена спутников должны быть уникальны и отличаться от имени героя.")
            names.add(name.casefold())

    def to_dict(self) -> dict:
        return dict(world=self.world, story=self.story, character=self.character.to_dict(),
                    companions=[companion.to_dict() for companion in self.companions])

    @classmethod
    def from_dict(cls, data: dict) -> "GameSetup":
        return cls(world=data["world"], story=data["story"],
                   character=Character.from_dict(data["character"]),
                   companions=tuple(Companion.from_dict(item) for item in data.get("companions", [])))
