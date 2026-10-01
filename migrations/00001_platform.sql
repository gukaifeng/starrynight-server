-- +goose Up
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE users (
    id uuid PRIMARY KEY,
    username text UNIQUE CHECK (username IS NULL OR username ~ '^[a-z0-9_]{3,32}$'),
    password_hash text,
    guest boolean NOT NULL DEFAULT false,
    session_epoch bigint NOT NULL DEFAULT 1,
    profile jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(profile) = 'object'),
    version bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK ((guest AND username IS NULL AND password_hash IS NULL) OR (NOT guest AND username IS NOT NULL AND password_hash IS NOT NULL))
);
CREATE TABLE identities (
    provider text NOT NULL,
    subject text NOT NULL,
    user_id uuid NOT NULL REFERENCES users ON DELETE CASCADE,
    verified_at timestamptz NOT NULL,
    PRIMARY KEY(provider,subject),
    UNIQUE(user_id,provider)
);
CREATE INDEX identities_user ON identities(user_id);
CREATE TABLE account_clocks (
    user_id uuid PRIMARY KEY REFERENCES users ON DELETE CASCADE,
    revision bigint NOT NULL DEFAULT 0
);
CREATE TABLE changes (
    user_id uuid NOT NULL REFERENCES users ON DELETE CASCADE,
    revision bigint NOT NULL,
    kind text NOT NULL,
    resource_id text NOT NULL,
    deleted boolean NOT NULL DEFAULT false,
    data jsonb NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(user_id,revision)
);
CREATE TABLE authors (
    id text PRIMARY KEY,
    user_id uuid UNIQUE REFERENCES users ON DELETE CASCADE,
    data jsonb NOT NULL CHECK (jsonb_typeof(data) = 'object'),
    version bigint NOT NULL DEFAULT 1,
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE characters (
    id text PRIMARY KEY,
    owner_id uuid REFERENCES users ON DELETE CASCADE,
    author_id text NOT NULL REFERENCES authors,
    base_id text REFERENCES characters,
    visibility text NOT NULL CHECK (visibility IN ('private','public','unlisted')),
    name text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 48),
    description text NOT NULL DEFAULT '',
    data jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(data) = 'object'),
    version bigint NOT NULL DEFAULT 1,
    deleted boolean NOT NULL DEFAULT false,
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX characters_owner ON characters(owner_id,id);
CREATE INDEX characters_author ON characters(author_id,id) WHERE NOT deleted;
CREATE INDEX characters_base ON characters(base_id);
CREATE INDEX characters_market ON characters(id) WHERE visibility='public' AND NOT deleted;
CREATE INDEX characters_search ON characters USING gin ((name || ' ' || description) gin_trgm_ops) WHERE visibility='public' AND NOT deleted;
CREATE TABLE subscriptions (
    user_id uuid NOT NULL REFERENCES users ON DELETE CASCADE,
    character_id text NOT NULL REFERENCES characters ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(user_id,character_id)
);
CREATE INDEX subscriptions_character ON subscriptions(character_id,user_id);
CREATE TABLE follows (
    user_id uuid NOT NULL REFERENCES users ON DELETE CASCADE,
    author_id text NOT NULL REFERENCES authors ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(user_id,author_id)
);
CREATE INDEX follows_author ON follows(author_id,user_id);
CREATE TABLE settings (
    user_id uuid PRIMARY KEY REFERENCES users ON DELETE CASCADE,
    data jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(data) = 'object'),
    version bigint NOT NULL DEFAULT 1
);
CREATE TABLE preferences (
    user_id uuid NOT NULL REFERENCES users ON DELETE CASCADE,
    character_id text NOT NULL REFERENCES characters ON DELETE CASCADE,
    data jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(data) = 'object'),
    version bigint NOT NULL DEFAULT 1,
    PRIMARY KEY(user_id,character_id)
);
CREATE INDEX preferences_character ON preferences(character_id);
CREATE TABLE conversations (
    user_id uuid NOT NULL REFERENCES users ON DELETE CASCADE,
    character_id text NOT NULL REFERENCES characters ON DELETE CASCADE,
    hidden boolean NOT NULL DEFAULT false,
    pinned boolean NOT NULL DEFAULT false,
    version bigint NOT NULL DEFAULT 1,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(user_id,character_id)
);
CREATE INDEX conversations_character ON conversations(character_id);
CREATE INDEX conversations_recent ON conversations(user_id,updated_at DESC,character_id);
CREATE TABLE messages (
    user_id uuid NOT NULL,
    character_id text NOT NULL,
    id uuid NOT NULL,
    sequence bigint GENERATED ALWAYS AS IDENTITY,
    role text NOT NULL CHECK (role IN ('user','assistant')),
    text text NOT NULL CHECK (char_length(text) <= 32000),
    data jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(data) = 'object'),
    version bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL,
    PRIMARY KEY(user_id,character_id,id),
    FOREIGN KEY(user_id,character_id) REFERENCES conversations ON DELETE CASCADE
);
CREATE INDEX messages_page ON messages(user_id,character_id,sequence);
CREATE INDEX messages_search ON messages USING gin(text gin_trgm_ops);
CREATE TABLE entries (
    user_id uuid NOT NULL,
    character_id text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('memory','moment')),
    id uuid NOT NULL,
    data jsonb NOT NULL CHECK (jsonb_typeof(data) = 'object'),
    version bigint NOT NULL DEFAULT 1,
    PRIMARY KEY(user_id,character_id,kind,id),
    FOREIGN KEY(user_id,character_id) REFERENCES conversations ON DELETE CASCADE
);

-- Text metadata only; no third-party model binaries, textures or motion data.
INSERT INTO authors(id,data) VALUES ('starry-studio','{"name":"星夜","bio":"认真打磨每一次相遇。","avatar":"starry"}');
INSERT INTO characters(id,author_id,visibility,name,description,data) VALUES
('anime-kipfel','starry-studio','public','琪宝','可爱的日系二次元伙伴','{"runtime_id":"anime-kipfel","asset_delivery":"bundled","schema_version":1}'),
('anime-mamehinata','starry-studio','public','豆日向','温暖的日系二次元伙伴','{"runtime_id":"anime-mamehinata","asset_delivery":"bundled","schema_version":1}');

-- +goose Down
DROP TABLE entries,messages,conversations,preferences,settings,follows,subscriptions,characters,authors,changes,account_clocks,identities,users;
