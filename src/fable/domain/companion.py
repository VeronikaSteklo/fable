"""Companion profiles and their evolving relationship with the hero."""
from dataclasses import asdict, dataclass, field

from fable.domain.events import (DomainEvent, CompanionAttitudeChanged, CompanionLearned,
                                 CompanionLeft, CompanionReturned)


class InvalidSetupError(ValueError):
    """Настройки игры нарушают правила создания спутников."""


@dataclass(frozen=True)
class Companion:
    name: str
    role: str
    personality: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Companion":
        return cls(name=data["name"], role=data["role"], personality=data["personality"])


@dataclass(frozen=True)
class Attitude:
    value: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", max(-100, min(100, self.value)))

    def changed(self, delta: int) -> "Attitude":
        return Attitude(self.value + delta)

    @property
    def label(self) -> str:
        if self.value <= -60:
            return "враждебно"
        if self.value <= -20:
            return "настороженно"
        if self.value < 20:
            return "нейтрально"
        if self.value < 60:
            return "дружелюбно"
        return "доверяет"


@dataclass
class CompanionState:
    name: str
    role: str
    attitude: Attitude = field(default_factory=Attitude)
    present: bool = True
    notes: list[str] = field(default_factory=list)
    _events: list[DomainEvent] = field(default_factory=list, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        notes, self.notes = self.notes, []
        for note in notes:
            self.remember(note)
        self._events.clear()  # Rehydration is not a change in the story.

    def change_attitude(self, delta: int) -> None:
        previous = self.attitude.value
        self.attitude = self.attitude.changed(max(-25, min(25, delta)))
        if self.attitude.value != previous:
            self._events.append(CompanionAttitudeChanged(
                self.name, self.attitude.value - previous, self.attitude.value, self.attitude.label,
            ))

    def remember(self, note: str) -> None:
        note = note.strip()
        if note and note.casefold() not in {entry.casefold() for entry in self.notes}:
            self.notes.append(note)
            self.notes = self.notes[-20:]
            self._events.append(CompanionLearned(self.name, note))

    def set_present(self, present: bool) -> None:
        if self.present != present:
            self.present = present
            self._events.append(CompanionReturned(self.name) if present else CompanionLeft(self.name))

    def pull_events(self) -> list[DomainEvent]:
        events, self._events = self._events, []
        return events

    def to_dict(self) -> dict:
        return dict(name=self.name, role=self.role, attitude=self.attitude.value,
                    attitude_label=self.attitude.label, present=self.present, notes=list(self.notes))

    @classmethod
    def from_dict(cls, data: dict) -> "CompanionState":
        return cls(name=data["name"], role=data["role"], attitude=Attitude(data.get("attitude", 0)),
                   present=data.get("present", True), notes=list(data.get("notes", [])))

    def to_context(self) -> str:
        status = "рядом" if self.present else "не рядом"
        notes = "; ".join(self.notes[-5:]) or "пока нет"
        return (f"{self.name} ({self.role}): {self.attitude.label} ({self.attitude.value}), "
                f"{status}. Заметки: {notes}")
