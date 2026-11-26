import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from types import SimpleNamespace
from unittest.mock import Mock, patch

from fable.infrastructure.llm.embeddings import OpenAIEmbeddings, create_embeddings
from fable.config import Settings


class FakeEmbeddings(OpenAIEmbeddings):
    def __init__(self, size):
        self.client = SimpleNamespace(embeddings=SimpleNamespace(create=self.create))
        self.model = 'fake'
        self.size = size

    def create(self, *, model, input):
        return SimpleNamespace(data=[SimpleNamespace(index=i, embedding=[1.0] * self.size)
                                     for i, text in enumerate(input)])

from fable.domain.game.setup import Character, GameSetup
from fable.infrastructure.memory.chroma import ChromaMemory


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
    def test_sdk_embeddings_and_endpoint_selection(self):
        client = Mock()
        client.embeddings.create.return_value = SimpleNamespace(data=[
            SimpleNamespace(index=1, embedding=[2.0]), SimpleNamespace(index=0, embedding=[1.0])])
        embeddings = OpenAIEmbeddings(client, 'embed')
        self.assertEqual(embeddings.embed_documents(['one', 'two']), [[1.0], [2.0]])
        client.embeddings.create.assert_called_once_with(model='embed', input=['one', 'two'])
        for url in (None, 'http://embeddings.invalid/v1'):
            config = Settings(_env_file=None, api_key='fake', base_url='http://offline.invalid', model='test',
                              embedding_model='embed', embedding_base_url=url)
            with patch('fable.infrastructure.llm.embeddings.build_client') as build:
                adapter = create_embeddings(config)
            build.assert_called_once_with(config, base_url=url or config.base_url)
            self.assertEqual(adapter.model, 'embed')

    def test_empty_inputs_and_campaign_filter(self):
        collection = Mock()
        collection.query.return_value = {'documents': [['event']]}
        with patch('fable.infrastructure.memory.chroma.chromadb.PersistentClient') as client:
            client.return_value.get_or_create_collection.return_value = collection
            memory = ChromaMemory(make_setup(), FakeEmbeddings(8), Path('unused'), 3)
        client.assert_called_once_with(path='unused')
        self.assertEqual(memory.search(' '), [])
        with self.assertRaises(ValueError):
            memory.remember(' ')
        collection.query.assert_not_called()
        memory.remember(' event ')
        self.assertEqual(collection.add.call_args.kwargs['documents'], ['event'])
        self.assertEqual(memory.search('query'), ['event'])
        self.assertEqual(collection.query.call_args.kwargs['where'], {'campaign_id': memory._campaign_id})
        self.assertEqual(collection.query.call_args.kwargs['n_results'], 3)

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
