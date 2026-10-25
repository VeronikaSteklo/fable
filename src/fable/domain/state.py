from dataclasses import dataclass, field


@dataclass
class GameState:
    location: str | None = None
    inventory: list[str] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)

    def update(
        self,
        *,
        location: str | None = None,
        add_inventory: list[str] | None = None,
        remove_inventory: list[str] | None = None,
        add_facts: list[str] | None = None,
    ) -> None:
        if location and location.strip():
            self.location = location.strip()

        removals = {item.strip().casefold() for item in remove_inventory or []}
        self.inventory = [item for item in self.inventory if item.casefold() not in removals]
        for item in add_inventory or []:
            item = item.strip()
            if item and item.casefold() not in {entry.casefold() for entry in self.inventory}:
                self.inventory.append(item)

        existing_facts = {fact.casefold() for fact in self.facts}
        for fact in add_facts or []:
            fact = fact.strip()
            if fact and fact.casefold() not in existing_facts:
                self.facts.append(fact)
                existing_facts.add(fact.casefold())

    def to_context(self) -> str:
        location = self.location or "неизвестна"
        inventory = ", ".join(self.inventory) if self.inventory else "пусто"
        facts = "\n".join(f"- {fact}" for fact in self.facts) or "- пока нет"
        return (
            f"Текущая локация: {location}\n"
            f"Инвентарь: {inventory}\n"
            f"Установленные факты:\n{facts}"
        )
