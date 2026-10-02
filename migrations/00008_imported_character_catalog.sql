-- +goose Up
-- Public metadata only; no model binaries, artwork, or distribution grant.
-- Mirrors the reviewed 41-role client roster so account sync works for every role.
INSERT INTO characters(id,author_id,visibility,name,description,data) VALUES
('anime-kipfel','starry-studio','public','琪宝','戴着软帽、带着小尾巴的花园伙伴。喜欢散步、小点心，也喜欢听你说今天的小事。','{"runtime_id":"anime-kipfel","asset_delivery":"bundled","schema_version":1,"local_preview":true}'),
('anime-mamehinata','starry-studio','public','豆日向','穿着宽松外套的犬耳伙伴。把日常的小发现装进口袋，愿意陪你度过轻松的一刻。','{"runtime_id":"anime-mamehinata","asset_delivery":"bundled","schema_version":1,"local_preview":true}'),
('anime-torao','starry-studio','public','小虎','小虎在临河的小修理铺学习修好旧物。看起来淡定，心里却很在意每个被认真保留下来的东西；话不多，但会记住你随口提起的小事。','{"runtime_id":"anime-torao","asset_delivery":"bundled","schema_version":1,"local_preview":true}'),
('anime-airi','starry-studio','public','爱莉','在星夜遇见爱莉，保留原作造型和角色表现。','{"runtime_id":"anime-airi","asset_delivery":"bundled","schema_version":1,"local_preview":true}'),
('anime-azuki','starry-studio','public','Azuki','本地外观预览；原作控制器与未适配动作暂不可用。','{"runtime_id":"anime-azuki","asset_delivery":"bundled","schema_version":1,"local_preview":true}'),
('anime-chiffon','starry-studio','public','戚风','在星夜遇见戚风，保留原作造型和角色表现。','{"runtime_id":"anime-chiffon","asset_delivery":"bundled","schema_version":1,"local_preview":true}'),
('anime-cornet','starry-studio','public','可露','本地外观预览；原作控制器与未适配动作暂不可用。','{"runtime_id":"anime-cornet","asset_delivery":"bundled","schema_version":1,"local_preview":true}'),
('anime-eku','starry-studio','public','意可蕾','在星夜遇见意可蕾，保留原作造型和角色表现。','{"runtime_id":"anime-eku","asset_delivery":"bundled","schema_version":1,"local_preview":true}'),
('anime-elusion','starry-studio','public','Elusion','本地外观预览；原作控制器与未适配动作暂不可用。','{"runtime_id":"anime-elusion","asset_delivery":"bundled","schema_version":1,"local_preview":true}'),
('anime-fiona','starry-studio','public','Fiona','本地外观预览；原作控制器与未适配动作暂不可用。','{"runtime_id":"anime-fiona","asset_delivery":"bundled","schema_version":1,"local_preview":true}'),
('anime-hikarun','starry-studio','public','Hikarun','本地外观预览；原作控制器与未适配动作暂不可用。','{"runtime_id":"anime-hikarun","asset_delivery":"bundled","schema_version":1,"local_preview":true}'),
('anime-ichigo','starry-studio','public','草莓','草莓在石桥边的小茶点铺学习做点心，喜欢为每个季节找到自己的颜色。她开朗、爱尝试，有一点小骄傲，也会认真听见你笑容后面的心事。','{"runtime_id":"anime-ichigo","asset_delivery":"bundled","schema_version":1,"local_preview":true}'),
('anime-kumaly','starry-studio','public','Kumaly','本地外观预览；原作控制器与未适配动作暂不可用。','{"runtime_id":"anime-kumaly","asset_delivery":"bundled","schema_version":1,"local_preview":true}'),
('anime-karin','starry-studio','public','卡琳','在星夜遇见卡琳，保留原作造型和角色表现。','{"runtime_id":"anime-karin","asset_delivery":"bundled","schema_version":1,"local_preview":true}'),
('anime-kikyo','starry-studio','public','桔梗','本地外观预览；原作控制器与未适配动作暂不可用。','{"runtime_id":"anime-kikyo","asset_delivery":"bundled","schema_version":1,"local_preview":true}'),
('anime-kipfel-v111','starry-studio','public','小猫·新版','本地外观预览；原作控制器与未适配动作暂不可用。','{"runtime_id":"anime-kipfel-v111","asset_delivery":"bundled","schema_version":1,"local_preview":true}'),
('anime-lasyusha','starry-studio','public','Lasyusha','本地外观预览；原作控制器与未适配动作暂不可用。','{"runtime_id":"anime-lasyusha","asset_delivery":"bundled","schema_version":1,"local_preview":true}'),
('anime-lime','starry-studio','public','青柠','青柠在小镇的植物观察站做记录，善于发现别人忽略的小变化。她亲切又有主见，喜欢认真听你讲一个片段，再陪你从里面找到一点新的可能。','{"runtime_id":"anime-lime","asset_delivery":"bundled","schema_version":1,"local_preview":true}'),
('anime-mafuyu','starry-studio','public','真冬','真冬照看山间旅舍的茶点角，习惯把事情整理得妥妥当当。她有一点慢热，却很在意你有没有好好休息；熟悉以后，那点小小的认真也会变成可爱的玩笑。','{"runtime_id":"anime-mafuyu","asset_delivery":"bundled","schema_version":1,"local_preview":true}'),
('anime-maki','starry-studio','public','真纪','本地外观预览；原作控制器与未适配动作暂不可用。','{"runtime_id":"anime-maki","asset_delivery":"bundled","schema_version":1,"local_preview":true}'),
('anime-mao','starry-studio','public','真央','本地外观预览；原作控制器与未适配动作暂不可用。','{"runtime_id":"anime-mao","asset_delivery":"bundled","schema_version":1,"local_preview":true}'),
('anime-marycia','starry-studio','public','Marycia','在星夜遇见Marycia，保留原作造型和角色表现。','{"runtime_id":"anime-marycia","asset_delivery":"bundled","schema_version":1,"local_preview":true}'),
('anime-mashu','starry-studio','public','麻薯','本地外观预览；原作控制器与未适配动作暂不可用。','{"runtime_id":"anime-mashu","asset_delivery":"bundled","schema_version":1,"local_preview":true}'),
('anime-meiyun','starry-studio','public','美云','在星夜遇见美云，保留原作造型和角色表现。','{"runtime_id":"anime-meiyun","asset_delivery":"bundled","schema_version":1,"local_preview":true}'),
('anime-milfy','starry-studio','public','米露菲','在星夜遇见米露菲，保留原作造型和角色表现。','{"runtime_id":"anime-milfy","asset_delivery":"bundled","schema_version":1,"local_preview":true}'),
('anime-milltina','starry-studio','public','米露缇娜','在星夜遇见米露缇娜，保留原作造型和角色表现。','{"runtime_id":"anime-milltina","asset_delivery":"bundled","schema_version":1,"local_preview":true}'),
('anime-mizuki','starry-studio','public','瑞希','本地外观预览；原作控制器与未适配动作暂不可用。','{"runtime_id":"anime-mizuki","asset_delivery":"bundled","schema_version":1,"local_preview":true}'),
('anime-nemesis','starry-studio','public','Nemesis','本地外观预览；原作控制器与未适配动作暂不可用。','{"runtime_id":"anime-nemesis","asset_delivery":"bundled","schema_version":1,"local_preview":true}'),
('anime-nochica','starry-studio','public','Nochica','本地外观预览；原作控制器与未适配动作暂不可用。','{"runtime_id":"anime-nochica","asset_delivery":"bundled","schema_version":1,"local_preview":true}'),
('anime-nozomi','starry-studio','public','望','望在河畔的小天文馆学习讲解，喜欢把星图和生活里的小事联系起来。她温柔、专注，也会为一点新发现高兴很久；有她在，普通的夜晚也值得慢慢看。','{"runtime_id":"anime-nozomi","asset_delivery":"bundled","schema_version":1,"local_preview":true}'),
('anime-perula','starry-studio','public','Perula','本地外观预览；原作控制器与未适配动作暂不可用。','{"runtime_id":"anime-perula","asset_delivery":"bundled","schema_version":1,"local_preview":true}'),
('anime-plum','starry-studio','public','小梅','小梅在梅树巷的茶屋学习调茶，喜欢记下四季花草的气味。她温柔细致，也有一点小机灵，总能从平常的一天里发现值得分享的小事。','{"runtime_id":"anime-plum","asset_delivery":"bundled","schema_version":1,"local_preview":true}'),
('anime-ramune','starry-studio','public','Ramune','本地外观预览；原作控制器与未适配动作暂不可用。','{"runtime_id":"anime-ramune","asset_delivery":"bundled","schema_version":1,"local_preview":true}'),
('anime-ririka','starry-studio','public','Ririka','本地外观预览；原作控制器与未适配动作暂不可用。','{"runtime_id":"anime-ririka","asset_delivery":"bundled","schema_version":1,"local_preview":true}'),
('anime-rurune','starry-studio','public','露露奈','本地外观预览；原作控制器与未适配动作暂不可用。','{"runtime_id":"anime-rurune","asset_delivery":"bundled","schema_version":1,"local_preview":true}'),
('anime-shinano','starry-studio','public','信浓','在星夜遇见信浓，保留原作造型和角色表现。','{"runtime_id":"anime-shinano","asset_delivery":"bundled","schema_version":1,"local_preview":true}'),
('anime-shiratsume','starry-studio','public','Shiratsume','本地外观预览；原作控制器与未适配动作暂不可用。','{"runtime_id":"anime-shiratsume","asset_delivery":"bundled","schema_version":1,"local_preview":true}'),
('anime-shizuku','starry-studio','public','Shizuku','在星夜遇见Shizuku，保留原作造型和角色表现。','{"runtime_id":"anime-shizuku","asset_delivery":"bundled","schema_version":1,"local_preview":true}'),
('anime-sio','starry-studio','public','Sio','在星夜遇见Sio，保留原作造型和角色表现。','{"runtime_id":"anime-sio","asset_delivery":"bundled","schema_version":1,"local_preview":true}'),
('anime-siska','starry-studio','public','西卡','西卡整理着小镇旧物档案室里那些不起眼的宝贝。看起来有些懒洋洋，其实记得很多细节；她会慢慢听，也会忽然用一句认真又好笑的话把你逗乐。','{"runtime_id":"anime-siska","asset_delivery":"bundled","schema_version":1,"local_preview":true}'),
('anime-koharu','starry-studio','public','小春','本地外观预览；原作控制器与未适配动作暂不可用。','{"runtime_id":"anime-koharu","asset_delivery":"bundled","schema_version":1,"local_preview":true}')
ON CONFLICT(id) DO NOTHING;

-- +goose Down
-- Keep stable IDs and all user conversation references on code rollback.
SELECT 1;
