-- +goose Up
-- Text catalog only. This does not upload or distribute third-party avatar assets.
INSERT INTO characters(id,author_id,visibility,name,description,data) VALUES
('anime-chiffon','starry-studio','public','戚风','喜欢花草与手账的温柔伙伴','{"runtime_id":"anime-chiffon","asset_delivery":"bundled","schema_version":1,"local_preview":true}'),
('anime-karin','starry-studio','public','卡琳','喜欢画画与小发现的灵动伙伴','{"runtime_id":"anime-karin","asset_delivery":"bundled","schema_version":1,"local_preview":true}')
ON CONFLICT(id) DO NOTHING;

-- +goose Down
-- Intentionally retain catalog identity: rolling back application code must not
-- cascade-delete user subscriptions, conversations, memories, or preferences.
SELECT 1;
