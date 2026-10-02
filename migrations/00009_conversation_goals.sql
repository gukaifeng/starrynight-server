-- +goose Up
CREATE TABLE conversation_goals (
 user_id uuid NOT NULL REFERENCES users ON DELETE CASCADE,
 character_id text NOT NULL REFERENCES characters ON DELETE CASCADE,
 config jsonb NOT NULL CHECK(jsonb_typeof(config)='object'),
 progress jsonb NOT NULL DEFAULT '{}' CHECK(jsonb_typeof(progress)='object'),
 version bigint NOT NULL DEFAULT 1,
 progress_version bigint NOT NULL DEFAULT 0,
 PRIMARY KEY(user_id,character_id)
);
CREATE TABLE goal_turns (
 user_id uuid NOT NULL, character_id text NOT NULL, request_id uuid NOT NULL,
 config_version bigint NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(user_id,character_id,request_id),
 FOREIGN KEY(user_id,character_id) REFERENCES conversation_goals ON DELETE CASCADE
);
-- +goose Down
DROP TABLE goal_turns;
DROP TABLE conversation_goals;
