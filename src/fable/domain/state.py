from dataclasses import dataclass, field

from fable.domain.companion import CompanionState
from fable.domain.models import GameSetup
from fable.domain.events import DomainEvent, LocationChanged, ItemAcquired, ItemLost, FactEstablished


@dataclass
class GameState:
    location: str | None = None
    inventory: list[str] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)
    companions: list[CompanionState] = field(default_factory=list)
    _events: list[DomainEvent] = field(default_factory=list, init=False, repr=False, compare=False)

    @classmethod
    def for_setup(cls, setup: GameSetup) -> "GameState":
        return cls(companions=[CompanionState(item.name, item.role) for item in setup.companions])

    def companion(self, name: str) -> CompanionState | None:
        return next((item for item in self.companions
                     if item.name.casefold() == name.strip().casefold()), None)

    def update(
        self,
        *,
        location: str | None = None,
        add_inventory: list[str] | None = None,
        remove_inventory: list[str] | None = None,
        add_facts: list[str] | None = None,
    ) -> None:
        if location and location.strip() and location.strip() != self.location:
            self.location = location.strip()
            self._events.append(LocationChanged(self.location))

        removals = {item.strip().casefold() for item in remove_inventory or []}
        for item in self.inventory:
            if item.casefold() in removals:
                self._events.append(ItemLost(item))
        self.inventory = [item for item in self.inventory if item.casefold() not in removals]
        for item in add_inventory or []:
            item = item.strip()
            if (
                item
                and item.casefold() not in removals
                and item.casefold() not in {entry.casefold() for entry in self.inventory}
            ):
                self.inventory.append(item)
                self._events.append(ItemAcquired(item))

        existing_facts = {fact.casefold() for fact in self.facts}
        for fact in add_facts or []:
            fact = fact.strip()
            if fact and fact.casefold() not in existing_facts:
                self.facts.append(fact)
                existing_facts.add(fact.casefold())
                self._events.append(FactEstablished(fact))

    def pull_events(self) -> list[DomainEvent]:
        events, self._events = self._events, []
        for companion in self.companions:
            events.extend(companion.pull_events())
        return events

    def restore(self, snapshot: dict) -> None:
        """Rollback in place: tool closures must keep the same state reference."""
        restored = self.from_dict(snapshot)
        self.location = restored.location
        self.inventory = restored.inventory
        self.facts = restored.facts
        self.companions = restored.companions
        self._events.clear()

    def to_dict(self) -> dict:
        return {
            "location": self.location,
            "inventory": list(self.inventory),
            "facts": list(self.facts),
            "companions": [item.to_dict() for item in self.companions],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GameState":
        return cls(location=data.get("location"),
                   inventory=list(data.get("inventory", [])),
                   facts=list(data.get("facts", [])),
                   companions=[CompanionState.from_dict(item) for item in data.get("companions", [])])

    def to_context(self) -> str:
        location = self.location or "неизвестна"
        inventory = ", ".join(self.inventory) if self.inventory else "пусто"
        facts = "\n".join(f"- {fact}" for fact in self.facts) or "- пока нет"
        return (
            f"Текущая локация: {location}\n"
            f"Инвентарь: {inventory}\n"
            f"Установленные факты:\n{facts}"
            + ("\nСпутники:\n" + "\n".join(item.to_context() for item in self.companions)
               if self.companions else "")
        )
