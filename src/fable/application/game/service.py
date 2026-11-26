"""Framework-neutral campaign use cases and single-process concurrency boundary."""
from collections.abc import Callable, Generator, Iterator
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
import threading
from uuid import uuid4

from fable.application.safety.guardrails import BLOCK_MESSAGE
from fable.application.ports import GameRepository, Guardrail, StoredGame
from fable.application.game.session import GameSession
from fable.domain.companions.companion import InvalidSetupError
from fable.domain.safety.consistency import ConsistencyVerdict
from fable.domain.game.game import Game
from fable.domain.game.setup import GameSetup
from fable.domain.safety.safety import ContentBlockedError
from fable.domain.game.state import GameState


logger = logging.getLogger(__name__)


class GameError(Exception):
    pass


class GameNotFound(GameError):
    def __init__(self):
        super().__init__("Игра не найдена")


class GameBusy(GameError):
    def __init__(self):
        super().__init__("Ответ для этой игры уже генерируется")


class GameAlreadyStarted(GameError):
    def __init__(self):
        super().__init__("Игра уже началась")


class GameNotStarted(GameError):
    def __init__(self):
        super().__init__("Сначала начни игру")


class SetupRejected(GameError):
    def __init__(self):
        super().__init__(BLOCK_MESSAGE + " Измени описание мира или героя.")


class InvalidSetup(GameError):
    pass


class InvalidAction(GameError):
    def __init__(self):
        super().__init__("Введи какое-нибудь действие")


@dataclass
class LoadedGame:
    game: Game
    session: GameSession
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def setup(self) -> GameSetup:
        return self.game.setup

    @property
    def state(self) -> GameState:
        return self.game.state


@dataclass(frozen=True)
class Chunk:
    text: str


@dataclass(frozen=True)
class TurnCompleted:
    consistency: ConsistencyVerdict | None
    state: dict
    summary: str
    events: list[dict]
    usage: dict


@dataclass(frozen=True)
class TurnBlocked:
    message: str = BLOCK_MESSAGE


@dataclass(frozen=True)
class TurnFailed:
    message: str = "Не удалось продолжить историю. Попробуй ещё раз."


StreamItem = Chunk | TurnCompleted | TurnBlocked | TurnFailed


class TurnStream(Iterator[StreamItem]):
    """Own the eagerly acquired lock, even before first iteration.

    Callers must close on cancellation (or use the context manager). Closing an
    unstarted Python generator alone would not run its finally block.
    """
    def __init__(self, iterator: Generator[StreamItem, None, None], release: Callable[[], None]):
        self._iterator = iterator
        self._release = release

    def __iter__(self) -> "TurnStream":
        return self

    def __next__(self) -> StreamItem:
        return next(self._iterator)

    def close(self) -> None:
        try:
            self._iterator.close()
        finally:
            self._release()

    def __enter__(self) -> "TurnStream":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class GameService:
    def __init__(self, *, repository_factory: Callable[[str | None], GameRepository],
                 session_factory: Callable[[GameSetup, GameState, dict | None], GameSession],
                 guardrail: Guardrail,
                 normalize_setup: Callable[[GameSetup], GameSetup] = lambda setup: setup,
                 clock: Callable[[], str] | None = None,
                 id_factory: Callable[[], str] | None = None) -> None:
        self._repository = repository_factory
        self._session = session_factory
        self._guardrail = guardrail
        self._normalize = normalize_setup
        self._clock = clock or (lambda: datetime.now(timezone.utc).isoformat())
        self._id = id_factory or (lambda: uuid4().hex)
        self._loaded: dict[tuple[str | None, str], LoadedGame] = {}
        self._cache_lock = threading.Lock()

    def create_game(self, owner: str | None, setup: GameSetup) -> LoadedGame:
        try:
            setup = self._normalize(setup)
            setup.validate()
        except InvalidSetupError as error:
            raise InvalidSetup(str(error)) from error
        text = "\n".join([setup.world, setup.story, *setup.character.to_dict().values(),
                          *(value for item in setup.companions for value in item.to_dict().values())])
        if not self._guardrail.check(text).allowed:
            raise SetupRejected()
        game = Game.create(self._id(), owner, setup, self._clock())
        loaded = LoadedGame(game, self._session(setup, game.state, None))
        self._repository(owner).add(StoredGame(game, loaded.session.to_snapshot()))
        with self._cache_lock:
            self._loaded[(owner, game.id)] = loaded
        return loaded

    def list_games(self, owner: str | None) -> list[dict]:
        return self._repository(owner).list_summaries()

    def get_game(self, owner: str | None, game_id: str) -> LoadedGame:
        key = (owner, game_id)
        # Serialize restoration so first concurrent requests share one lock.
        with self._cache_lock:
            if key not in self._loaded:
                try:
                    stored = self._repository(owner).get(game_id)
                except ValueError:
                    raise GameNotFound() from None
                if stored is None or stored.game.owner_id not in (None, owner):
                    raise GameNotFound()
                game = stored.game
                self._loaded[key] = LoadedGame(game, self._session(game.setup, game.state, stored.session))
            return self._loaded[key]

    def _acquire(self, owner: str | None, game_id: str, loaded: LoadedGame) -> None:
        with self._cache_lock:
            if self._loaded.get((owner, game_id)) is not loaded:
                raise GameNotFound()
            if not loaded.lock.acquire(blocking=False):
                raise GameBusy()

    def delete_game(self, owner: str | None, game_id: str) -> None:
        loaded = self.get_game(owner, game_id)
        self._acquire(owner, game_id, loaded)
        try:
            with self._cache_lock:
                self._repository(owner).delete(game_id)
                self._loaded.pop((owner, game_id), None)
        finally:
            loaded.lock.release()

    def start_stream(self, owner: str | None, game_id: str) -> TurnStream:
        return self._turn_stream(owner, game_id)

    def play_turn_stream(self, owner: str | None, game_id: str, action: str) -> TurnStream:
        # Hidden games take precedence over action validation.
        self.get_game(owner, game_id)
        action = action.strip()
        if not action:
            raise InvalidAction()
        return self._turn_stream(owner, game_id, action)

    def _turn_stream(self, owner: str | None, game_id: str, action: str | None = None) -> TurnStream:
        loaded = self.get_game(owner, game_id)
        self._acquire(owner, game_id, loaded)
        release_lock = threading.Lock()
        released = False

        def release() -> None:
            nonlocal released
            with release_lock:
                if not released:
                    released = True
                    loaded.lock.release()

        try:
            if action is None and loaded.session.started:
                raise GameAlreadyStarted()
            if action is not None and not loaded.session.started:
                raise GameNotStarted()
            before = loaded.session.to_snapshot()
            state_before = loaded.state.to_dict()
            updated_before = loaded.game.updated_at
        except BaseException:
            release()
            raise

        def generate() -> Generator[StreamItem, None, None]:
            successful = False
            reply = None
            try:
                reply = (loaded.session.start_stream() if action is None
                         else loaded.session.send_action_stream(action))
                for chunk in reply:
                    yield Chunk(chunk)
                events = [event.to_dict() for event in loaded.game.pull_events()]
                loaded.session.attach_events(events)
                loaded.game.updated_at = self._clock()
                self._repository(owner).save(StoredGame(loaded.game, loaded.session.to_snapshot()))
                successful = True
                usage = loaded.session.last_usage
                assert usage is not None
                yield TurnCompleted(loaded.session.last_verdict, loaded.state.to_dict(),
                                    loaded.session.summary, deepcopy(events), deepcopy(usage))
            except ContentBlockedError:
                yield TurnBlocked()
            except Exception:
                logger.exception("Не удалось завершить ход игры %s", game_id)
                yield TurnFailed()
            finally:
                try:
                    try:
                        if reply is not None:
                            reply.close()
                    finally:
                        if not successful:
                            loaded.state.restore(state_before)
                            loaded.game.updated_at = updated_before
                            loaded.session = self._session(loaded.setup, loaded.state, before)
                finally:
                    release()

        return TurnStream(generate(), release)
