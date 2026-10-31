import json
import unittest

from fable.application.session import GameSession
from fable.domain.consistency import ConsistencyVerdict
from test_consistency import SequenceChecker
from test_session import FakeAgent
from test_session_memory import FakeSummarizer


class SnapshotTests(unittest.TestCase):
    def test_round_trip_preserves_summary_pending_note_and_outgoing_messages(self):
        checker = SequenceChecker([
            *[ConsistencyVerdict.ok()] * 3,
            ConsistencyVerdict(False, ("Ошибка",)),
            ConsistencyVerdict.ok(),
        ])
        agent = FakeAgent(["Начало", "Один", "Два", "Три", "Четыре"])
        session = GameSession(agent, 4, summarizer=FakeSummarizer(), checker=checker)
        self.assertFalse(session.started)
        session.start()
        for action in ["1", "2", "3"]:
            session.send_action(action)
        snapshot = json.loads(json.dumps(session.to_snapshot(), ensure_ascii=False))
        restored_agent = FakeAgent(["Четыре"])
        restored = GameSession.from_snapshot(snapshot, agent=restored_agent, history_limit=4,
                                             summarizer=FakeSummarizer(),
                                             checker=SequenceChecker([ConsistencyVerdict.ok()]))
        self.assertTrue(restored.started)
        self.assertEqual(restored.to_snapshot(), snapshot)
        self.assertEqual(restored.summary, session.summary)
        self.assertEqual(restored.last_verdict, session.last_verdict)
        # Runtime dependencies are supplied again; no model objects in the snapshot.
        session.send_action("4")
        restored.send_action("4")
        self.assertEqual(restored_agent.requests[-1], agent.requests[-1])
        self.assertEqual(restored.to_snapshot(), session.to_snapshot())

    def test_snapshots_are_detached_and_unstarted_session_restores(self):
        session = GameSession(FakeAgent([]), 4)
        snapshot = session.to_snapshot()
        restored = GameSession.from_snapshot(snapshot, agent=FakeAgent([]), history_limit=4)
        snapshot["history"][0]["content"] = "Изменено"
        self.assertNotEqual(restored.to_snapshot(), snapshot)
        self.assertNotEqual(session.to_snapshot(), snapshot)
        self.assertFalse(restored.started)

    def test_invalid_summary_pointer_is_rejected(self):
        session = GameSession(FakeAgent([]), 4)
        for pointer in [-1, 5, True]:
            snapshot = session.to_snapshot()
            snapshot["summarized_count"] = pointer
            with self.subTest(pointer=pointer), self.assertRaises(ValueError):
                GameSession.from_snapshot(snapshot, agent=FakeAgent([]), history_limit=4)
