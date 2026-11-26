"""Explicit SDK embeddings: Chroma never downloads a default embedding model."""
from dataclasses import dataclass

from openai import OpenAI

from fable.config import Settings
from fable.infrastructure.llm.client import build_client


@dataclass
class OpenAIEmbeddings:
    client: OpenAI
    model: str

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        result = self.client.embeddings.create(model=self.model, input=texts)
        return [item.embedding for item in sorted(result.data, key=lambda item: item.index)]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


def create_embeddings(settings: Settings) -> OpenAIEmbeddings:
    if not settings.embedding_model:
        raise ValueError('Не задан EMBEDDING_MODEL')
    return OpenAIEmbeddings(build_client(settings, base_url=settings.embedding_base_url or settings.base_url),
                            settings.embedding_model)
