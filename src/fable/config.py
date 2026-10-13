import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    base_url: str
    model: str
    api_key: str

    @classmethod
    def from_environment(cls) -> "Settings":
        load_dotenv()

        values = {
            "BASE_URL": os.getenv("BASE_URL", "").strip(),
            "MODEL": os.getenv("MODEL", "").strip(),
            "API_KEY": os.getenv("API_KEY", "").strip(),
        }
        missing_settings = [
            name for name, value in values.items() if not value or value.lower().startswith("your_")
        ]
        if missing_settings:
            raise ValueError("Заполни настройки в .env: " + ", ".join(missing_settings))

        return cls(
            base_url=values["BASE_URL"],
            model=values["MODEL"],
            api_key=values["API_KEY"],
        )
