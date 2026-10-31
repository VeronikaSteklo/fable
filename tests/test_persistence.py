import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fable.application.persistence import build_game_record, parse_game_record
from fable.application.session import GameSession
from fable.domain.models import Character, GameSetup
from fable.domain.state import GameState
from fable.infrastructure.session_store import JsonSessionStore
from test_session import FakeAgent


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(dir=os.environ["TMPDIR"])
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name) / "sessions"
        self.setup = GameSetup("Мир", "История", Character("Мира", "Маг", "Цель", "", "Фэнтези"))
        self.state = GameState("Башня", ["Ключ"], ["Дверь закрыта"])
        self.session = GameSession(FakeAgent(["Начало", "Ответ"]), 4)
        self.session.start()
        self.session.send_action("Открыть дверь")

    def record(self, game_id="game_1", updated_at="2026-10-30T10:00:00+00:00"):
        return build_game_record(game_id, self.setup, self.state, self.session,
                                 created_at="2026-10-30T09:00:00+00:00", updated_at=updated_at)

    def test_record_build_and_parse(self):
        record = self.record()
        parsed = parse_game_record(json.loads(json.dumps(record, ensure_ascii=False)))
        self.assertEqual(parsed.id, "game_1")
        self.assertEqual(parsed.setup, self.setup)
        self.assertEqual(parsed.state, self.state)
        self.assertEqual(parsed.session, self.session.to_snapshot())
        self.assertEqual(parsed.created_at, record["created_at"])
        self.assertEqual(parsed.updated_at, record["updated_at"])
        fresh = build_game_record("new", self.setup, self.state, self.session)
        self.assertEqual(fresh["created_at"], fresh["updated_at"])
        self.assertTrue(fresh["updated_at"])

    def test_save_load_list_delete(self):
        store = JsonSessionStore(self.directory)
        record = self.record()
        self.assertIsNone(store.load("missing"))
        self.assertEqual(store.list(), [])
        store.save("game_1", record)
        self.assertEqual(store.load("game_1"), record)
        self.assertIn("Мира", (self.directory / "game_1.json").read_text(encoding="utf-8"))
        store.save("game_2", self.record("game_2", "2026-10-30T11:00:00+00:00"))
        listed = store.list()
        self.assertEqual([item["id"] for item in listed], ["game_2", "game_1"])
        self.assertEqual(listed[1], {"id": "game_1", "title": "Мира", "character_name": "Мира",
                                     "updated_at": record["updated_at"], "turns": 1})
        store.save("game_1", self.record(updated_at="2026-10-30T12:00:00+00:00"))
        self.assertEqual(store.list()[0]["id"], "game_1")
        store.delete("game_1")
        self.assertIsNone(store.load("game_1"))
        store.delete("game_1")
        self.assertEqual(len(store.list()), 1)

    def test_invalid_ids_are_rejected_for_all_operations(self):
        store = JsonSessionStore(self.directory)
        for game_id in ["", "../outside", "/absolute", "a/b", "a\\b", ".", "..", "bad.json", "кириллица", "a" * 129]:
            for operation in [lambda: store.save(game_id, self.record()),
                              lambda: store.load(game_id), lambda: store.delete(game_id)]:
                with self.subTest(game_id=game_id), self.assertRaises(ValueError):
                    operation()
        self.assertEqual(store.list(), [])

    def test_atomic_replace_failure_preserves_old_record_and_cleans_temp(self):
        store = JsonSessionStore(self.directory)
        record = self.record()
        store.save("game_1", record)
        with patch("fable.infrastructure.session_store.os.replace", side_effect=OSError("сбой")):
            with self.assertRaises(OSError):
                store.save("game_1", self.record(updated_at="later"))
        self.assertEqual(store.load("game_1"), record)
        self.assertEqual(sorted(p.name for p in self.directory.iterdir()), ["game_1.json"])

    def test_list_skips_corrupt_files(self):
        store = JsonSessionStore(self.directory)
        (self.directory / "broken.json").write_text("not json", encoding="utf-8")
        store.save("game_1", self.record())
        with self.assertLogs("fable.infrastructure.session_store", "WARNING"):
            self.assertEqual(len(store.list()), 1)
