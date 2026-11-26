import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from langchain_core.embeddings import FakeEmbeddings

from fable.domain.models import Character, GameSetup
from fable.infrastructure.chroma_memory import ChromaMemory


def make_setup() -> GameSetup:
    return GameSetup(
        world="Королевство стеклянных городов",
        story="Пропала королева",
        character=Character(
            name="Мира",
            role="следопыт",
            goal="найти королеву",
            description="Любит старые карты",
            genre="фэнтези",
        ),
    )


class ChromaMemoryTests(unittest.TestCase):
    def test_memory_persists_and_is_scoped_to_campaign(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            setup = make_setup()
            memory = ChromaMemory(setup, FakeEmbeddings(size=8), path, search_limit=3)
            memory.remember("Мира нашла серебряный ключ в старой башне.")

            reopened_memory = ChromaMemory(setup, FakeEmbeddings(size=8), path, search_limit=3)
            recalled = reopened_memory.search("серебряный ключ")

            other_campaign = ChromaMemory(
                replace(setup, story="Экспедиция на север"),
                FakeEmbeddings(size=8),
                path,
                search_limit=3,
            )

            self.assertEqual(recalled, ["Мира нашла серебряный ключ в старой башне."])
            self.assertEqual(other_campaign.search("серебряный ключ"), [])


if __name__ == "__main__":
    unittest.main()
