import hashlib
import json
from pathlib import Path
from uuid import uuid4

from langchain_chroma import Chroma
from langchain_core.embeddings import Embeddings

from fable.domain.models import GameSetup


class ChromaMemory:
    def __init__(
        self,
        setup: GameSetup,
        embeddings: Embeddings,
        persist_directory: Path,
        search_limit: int,
    ):
        self._campaign_id = self._get_campaign_id(setup)
        self._search_limit = search_limit
        self._store = Chroma(
            collection_name="fable_story_memories",
            embedding_function=embeddings,
            persist_directory=str(persist_directory),
        )

    def remember(self, event: str) -> str:
        event = event.strip()
        if not event:
            raise ValueError("Нельзя сохранить пустое воспоминание.")

        self._store.add_texts(
            texts=[event],
            metadatas=[{"campaign_id": self._campaign_id}],
            ids=[str(uuid4())],
        )
        return "Сюжетное событие сохранено в памяти."

    def search(self, query: str) -> list[str]:
        query = query.strip()
        if not query:
            return []

        memories = self._store.similarity_search(
            query,
            k=self._search_limit,
            filter={"campaign_id": self._campaign_id},
        )
        return [memory.page_content for memory in memories]

    @staticmethod
    def _get_campaign_id(setup: GameSetup) -> str:
        character = setup.character
        campaign = {
            "world": setup.world,
            "story": setup.story,
            "character": {
                "name": character.name,
                "role": character.role,
                "goal": character.goal,
                "description": character.description,
                "genre": character.genre,
            },
        }
        canonical_campaign = json.dumps(
            campaign,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical_campaign.encode("utf-8")).hexdigest()
