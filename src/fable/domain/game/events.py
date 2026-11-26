"""Transient facts about actual changes, not commands or persisted world state."""
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from typing import ClassVar


@dataclass(frozen=True)
class DomainEvent(ABC):
    type: ClassVar[str]

    @abstractmethod
    def describe(self) -> str: ...

    def to_dict(self) -> dict:
        fields = asdict(self)
        if "name" in fields:
            fields["companion"] = fields.pop("name")
        return {"type": self.type, "text": self.describe(), **fields}


@dataclass(frozen=True)
class LocationChanged(DomainEvent):
    location: str
    type: ClassVar[str] = "location_changed"

    def describe(self) -> str:
        return f"Локация: {self.location}"


@dataclass(frozen=True)
class ItemAcquired(DomainEvent):
    item: str
    type: ClassVar[str] = "item_acquired"

    def describe(self) -> str:
        return f"Получен предмет: {self.item}"


@dataclass(frozen=True)
class ItemLost(DomainEvent):
    item: str
    type: ClassVar[str] = "item_lost"

    def describe(self) -> str:
        return f"Потерян предмет: {self.item}"


@dataclass(frozen=True)
class FactEstablished(DomainEvent):
    fact: str
    type: ClassVar[str] = "fact_established"

    def describe(self) -> str:
        return f"Установлен факт: {self.fact}"


@dataclass(frozen=True)
class CompanionAttitudeChanged(DomainEvent):
    name: str
    delta: int
    value: int
    label: str
    type: ClassVar[str] = "companion_attitude_changed"

    def describe(self) -> str:
        return f"{self.name}: отношение {self.delta:+d}, {self.label} ({self.value})"


@dataclass(frozen=True)
class CompanionLearned(DomainEvent):
    name: str
    note: str
    type: ClassVar[str] = "companion_learned"

    def describe(self) -> str:
        return f"{self.name} узнаёт: {self.note}"


@dataclass(frozen=True)
class CompanionLeft(DomainEvent):
    name: str
    type: ClassVar[str] = "companion_left"

    def describe(self) -> str:
        return f"{self.name} больше не рядом"


@dataclass(frozen=True)
class CompanionReturned(DomainEvent):
    name: str
    type: ClassVar[str] = "companion_returned"

    def describe(self) -> str:
        return f"{self.name} снова рядом"
