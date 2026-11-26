"""Plain SQL adapters. Pool connections are short-lived, never held during LLM I/O."""
from importlib.resources import files
import sqlite3

from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fable.application.game.persistence import parse_game_record
from fable.application.ports import StoredGame, PersistenceConflict
from fable.domain.game.game import Game
from fable.domain.users.user import User
from fable.infrastructure.persistence.auth_store import _token_hash
from fable.infrastructure.persistence.game_repository import stored_game_record


def migrate(pool) -> None:
    """One transaction, including the version table; serialize concurrent startups."""
    with pool.connection() as conn:
        with conn.transaction():
            conn.execute('SELECT pg_advisory_xact_lock(734120926)')
            conn.execute('''CREATE TABLE IF NOT EXISTS schema_migrations (
                name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())''')
            applied = {row[0] for row in conn.execute('SELECT name FROM schema_migrations')}
            for path in sorted(files(__package__).joinpath('migrations').iterdir(), key=lambda p: p.name):
                if path.name.endswith('.sql') and path.name not in applied:
                    conn.execute(path.read_text(encoding='utf-8'))
                    conn.execute('INSERT INTO schema_migrations (name) VALUES (%s)', (path.name,))


class PostgresAuthStore:
    def __init__(self, pool):
        self.pool = pool

    @staticmethod
    def _user(row):
        return User(row['id'], row['username'], row['created_at'].isoformat())

    def create_user(self, user, password_hash):
        try:
            with self.pool.connection() as conn:
                conn.execute('INSERT INTO users (id, username, password_hash, created_at) VALUES (%s,%s,%s,%s)',
                             (user.id, user.username, password_hash, user.created_at))
        except UniqueViolation as error:
            # Preserve the established AuthStore uniqueness contract.
            raise sqlite3.IntegrityError('username already exists') from error

    def find_by_username(self, username):
        with self.pool.connection() as conn:
            row = conn.cursor(row_factory=dict_row).execute(
                'SELECT * FROM users WHERE lower(username) = lower(%s)', (username,)).fetchone()
        return (self._user(row), row['password_hash']) if row else None

    def get_user(self, user_id):
        with self.pool.connection() as conn:
            row = conn.cursor(row_factory=dict_row).execute('SELECT * FROM users WHERE id = %s',
                                                          (user_id,)).fetchone()
        return self._user(row) if row else None

    def create_session(self, token, user_id, created_at, expires_at):
        with self.pool.connection() as conn:
            conn.execute('''INSERT INTO auth_sessions (token_hash, user_id, created_at, expires_at)
                            VALUES (%s,%s,%s,%s)''', (_token_hash(token), user_id, created_at, expires_at))

    def user_for_token(self, token, now):
        with self.pool.connection() as conn:
            conn.execute('DELETE FROM auth_sessions WHERE expires_at <= %s', (now,))
            row = conn.cursor(row_factory=dict_row).execute('''
                SELECT u.* FROM users u JOIN auth_sessions s ON u.id = s.user_id
                WHERE s.token_hash = %s AND s.expires_at > %s''', (_token_hash(token), now)).fetchone()
        return self._user(row) if row else None

    def delete_session(self, token):
        with self.pool.connection() as conn:
            conn.execute('DELETE FROM auth_sessions WHERE token_hash = %s', (_token_hash(token),))

    def prune_expired(self, now):
        with self.pool.connection() as conn:
            conn.execute('DELETE FROM auth_sessions WHERE expires_at <= %s', (now,))


class PostgresGameRepository:
    def __init__(self, pool, owner_id):
        self.pool, self.owner_id = pool, owner_id

    def get(self, game_id):
        with self.pool.connection() as conn:
            row = conn.cursor(row_factory=dict_row).execute('''
                SELECT * FROM games WHERE id = %s AND owner_id IS NOT DISTINCT FROM %s''',
                (game_id, self.owner_id)).fetchone()
        if row is None:
            return None
        row['created_at'] = row['created_at'].isoformat()
        row['updated_at'] = row['updated_at'].isoformat()
        parsed = parse_game_record(row)
        return StoredGame(Game(parsed.id, row['owner_id'], parsed.setup, parsed.state,
                               parsed.created_at, parsed.updated_at, row['version']), parsed.session)

    def _values(self, stored):
        if stored.game.owner_id != self.owner_id:
            raise ValueError('Игра принадлежит другому пользователю')
        record = stored_game_record(stored)
        history = record['session']['history']
        turns = sum(a['role'] == 'user' and b['role'] == 'assistant'
                    for a, b in zip(history[1:], history[2:]))
        return (stored.game.setup.character.name, record['updated_at'], Jsonb(record['setup']),
                Jsonb(record['state']), Jsonb(record['session']), turns)

    def add(self, stored):
        values = self._values(stored)
        try:
            with self.pool.connection() as conn:
                conn.execute('''INSERT INTO games
                    (title, updated_at, setup, state, session, turns, id, owner_id, created_at, version)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,1)''',
                    (*values, stored.game.id, self.owner_id, stored.game.created_at))
        except UniqueViolation as error:
            raise PersistenceConflict('Игра уже существует') from error
        stored.game.version = 1

    def save(self, stored):
        values = self._values(stored)
        with self.pool.connection() as conn:
            row = conn.execute('''UPDATE games SET title=%s, updated_at=%s, setup=%s, state=%s,
                session=%s, turns=%s, version=version+1
                WHERE id=%s AND owner_id IS NOT DISTINCT FROM %s AND version=%s RETURNING version''',
                (*values, stored.game.id, self.owner_id, stored.game.version)).fetchone()
            if row is None:
                raise PersistenceConflict('Игра была изменена другим процессом. Обнови страницу.')
        stored.game.version = row[0]

    def delete(self, game_id):
        with self.pool.connection() as conn:
            conn.execute('DELETE FROM games WHERE id=%s AND owner_id IS NOT DISTINCT FROM %s',
                         (game_id, self.owner_id))

    def list_summaries(self):
        with self.pool.connection() as conn:
            rows = conn.cursor(row_factory=dict_row).execute('''
                SELECT id, title, setup->'character'->>'name' AS character_name, updated_at, turns
                FROM games WHERE owner_id IS NOT DISTINCT FROM %s ORDER BY updated_at DESC''',
                (self.owner_id,)).fetchall()
        return [{**row, 'updated_at': row['updated_at'].isoformat()} for row in rows]
