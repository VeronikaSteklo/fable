CREATE TABLE users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE UNIQUE INDEX users_username_lower ON users (lower(username));
CREATE TABLE auth_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX auth_sessions_expiry ON auth_sessions (expires_at);
CREATE TABLE games (
    id TEXT PRIMARY KEY,
    owner_id TEXT REFERENCES users(id),
    title TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    setup JSONB NOT NULL,
    state JSONB NOT NULL,
    session JSONB NOT NULL,
    turns INTEGER NOT NULL DEFAULT 0 CHECK (turns >= 0),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0)
);
CREATE INDEX games_owner_updated ON games (owner_id, updated_at DESC);
