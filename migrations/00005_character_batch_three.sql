-- +goose Up
INSERT INTO characters(id,author_id,visibility,name,description,data) VALUES
('anime-plum','starry-studio','public','小梅','梅树巷的茶屋里，一起聊聊生活的小发现','{"runtime_id":"anime-plum","asset_delivery":"bundled","schema_version":1,"local_preview":true}')
ON CONFLICT(id) DO NOTHING;

-- +goose Down
-- Retain the stable identity and user conversation references on rollback.
SELECT 1;
