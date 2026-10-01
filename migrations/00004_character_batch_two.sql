-- +goose Up
-- Local preview metadata only; third-party models stay in private bundles.
INSERT INTO characters(id,author_id,visibility,name,description,data) VALUES
('anime-torao','starry-studio','public','小虎','夜间修理铺里，认真倾听的伙伴','{"runtime_id":"anime-torao","asset_delivery":"bundled","schema_version":1,"local_preview":true}'),
('anime-ichigo','starry-studio','public','草莓','把平凡午后做成甜点的小小创作者','{"runtime_id":"anime-ichigo","asset_delivery":"bundled","schema_version":1,"local_preview":true}'),
('anime-lime','starry-studio','public','青柠','和你一起发现新叶与生活的小变化','{"runtime_id":"anime-lime","asset_delivery":"bundled","schema_version":1,"local_preview":true}'),
('anime-mafuyu','starry-studio','public','真冬','雪后旅舍的一盏暖灯与一杯热饮','{"runtime_id":"anime-mafuyu","asset_delivery":"bundled","schema_version":1,"local_preview":true}'),
('anime-nozomi','starry-studio','public','望','在星空下陪你慢慢聊的观星向导','{"runtime_id":"anime-nozomi","asset_delivery":"bundled","schema_version":1,"local_preview":true}'),
('anime-siska','starry-studio','public','西卡','旧物档案室里，记得每件小事的伙伴','{"runtime_id":"anime-siska","asset_delivery":"bundled","schema_version":1,"local_preview":true}')
ON CONFLICT(id) DO NOTHING;

-- +goose Down
-- Preserve identity and user-owned subscriptions/conversations on rollback.
SELECT 1;
