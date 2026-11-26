import unittest
from unittest.mock import Mock

from fable.application.game.service import GameService, GameBusy, TurnCompleted
from fable.application.safety.guardrails import RuleGuardrail
from fable.domain.game.setup import GameSetup
from tests.application.game.test_game_service import MemoryRepository
from tests.application.test_bootstrap import settings
from tests.presentation.web.test_web import FakeFactory, EMPTY_SETUP


class DistributedServiceTests(unittest.TestCase):
    def service(self, repository, **kwargs):
        factory = FakeFactory()
        return GameService(repository_factory=lambda owner: repository,
                           session_factory=lambda setup, state, snapshot: factory(settings(), setup, state, snapshot),
                           guardrail=RuleGuardrail(), **kwargs)

    def test_injected_manager_busy_and_unstarted_close(self):
        locks = Mock()
        locks.try_acquire.return_value = None
        service = self.service(MemoryRepository(), lock_manager=locks)
        game = service.create_game('owner', GameSetup.from_dict(EMPTY_SETUP))
        with self.assertRaises(GameBusy):
            service.start_stream('owner', game.game.id)
        locks.try_acquire.return_value = 'token'
        stream = service.start_stream('owner', game.game.id)
        stream.close()
        stream.close()
        locks.release.assert_called_once_with('token')

    def test_turn_refreshes_after_lock_and_conflicts_roll_back(self):
        from copy import deepcopy
        from fable.application.ports import PersistenceConflict
        from fable.application.game.service import GameAlreadyStarted, TurnFailed
        repo = MemoryRepository()
        locks = Mock()
        locks.try_acquire.return_value = 'token'
        service = self.service(repo, reload_on_read=True, lock_manager=locks)
        game = service.create_game('owner', GameSetup.from_dict(EMPTY_SETUP))
        original = deepcopy(repo.records[game.game.id])

        def acquire(*args):
            repo.records[game.game.id].session['history'].append({'role': 'assistant', 'content': 'other worker'})
            return 'token'
        locks.try_acquire.side_effect = acquire
        with self.assertRaises(GameAlreadyStarted):
            service.start_stream('owner', game.game.id)
        locks.release.assert_called_once_with('token')
        repo.records[game.game.id] = original
        locks.try_acquire.side_effect = None
        repo.save = Mock(side_effect=PersistenceConflict('conflict'))
        stream = service.start_stream('owner', game.game.id)
        failed = list(stream)[-1]
        self.assertIsInstance(failed, TurnFailed)
        self.assertEqual(failed.status_code, 409)
        self.assertFalse(service.get_game('owner', game.game.id).session.started)

    def test_reload_observes_other_worker_changes(self):
        repo = MemoryRepository()
        a = self.service(repo, reload_on_read=True)
        b = self.service(repo, reload_on_read=True)
        game = a.create_game('owner', GameSetup.from_dict(EMPTY_SETUP))
        self.assertFalse(b.get_game('owner', game.game.id).session.started)
        self.assertIsInstance(list(a.start_stream('owner', game.game.id))[-1], TurnCompleted)
        self.assertTrue(b.get_game('owner', game.game.id).session.started)
