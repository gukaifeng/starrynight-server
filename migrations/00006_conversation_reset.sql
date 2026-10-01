-- +goose Up
-- A reset epoch fences out old offline outboxes after an explicit deletion.
CREATE TABLE conversation_resets (
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    character_id text NOT NULL,
    reset_id uuid NOT NULL,
    version bigint NOT NULL,
    cleared_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, character_id, reset_id),
    UNIQUE (user_id, character_id, version)
);

-- +goose Down
DROP TABLE conversation_resets;
