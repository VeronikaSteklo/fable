import hashlib
import json
from pathlib import Path
from uuid import uuid4

import chromadb

from fable.infrastructure.llm.embeddings import OpenAIEmbeddings

from fable.domain.game.setup import GameSetup


class ChromaMemory:
    def __init__(
        self,
        setup: GameSetup,
        embeddings: OpenAIEmbeddings,
        persist_directory: Path,
        search_limit: int,
    ):
        self._campaign_id = self._get_campaign_id(setup)
        self._search_limit = search_limit
        self._embeddings = embeddings
        self._client = chromadb.PersistentClient(path=str(persist_directory))
        self._store = self._client.get_or_create_collection(
            name="fable_story_memories", embedding_function=None,
        )

    def remember(self, event: str) -> str:
        event = event.strip()
        if not event:
            raise ValueError("Нельзя сохранить пустое воспоминание.")

        self._store.add(
            documents=[event],
            embeddings=self._embeddings.embed_documents([event]),
            metadatas=[{"campaign_id": self._campaign_id}],
            ids=[str(uuid4())],
        )
        return "Сюжетное событие сохранено в памяти."

    def search(self, query: str) -> list[str]:
        query = query.strip()
        if not query:
            return []

        memories = self._store.query(
            query_embeddings=[self._embeddings.embed_query(query)],
            n_results=self._search_limit,
            where={"campaign_id": self._campaign_id},
            include=['documents'],
        )
        documents = memories.get('documents')
        return list(documents[0]) if documents else []

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
