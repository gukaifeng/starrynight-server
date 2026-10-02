-- +goose Up
CREATE TABLE character_market_assets (
 character_id text PRIMARY KEY REFERENCES characters(id) ON DELETE CASCADE,
 data jsonb NOT NULL,
 updated_at timestamptz NOT NULL DEFAULT now()
);
-- +goose Down
DROP TABLE character_market_assets;
