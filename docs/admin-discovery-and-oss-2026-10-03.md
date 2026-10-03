# App 发现内容与 OSS 浏览

控制台左侧新增「App 发现页」与「OSS Bucket」，入口分别为管理站点的 `#discovery`、`#oss`。只修改独立服务端仓库，没有修改或重新发布客户端。

## 发现内容

发现页以电脑版卡片网格展示 App 的公开发现内容：完整角色名单、封面、名称和邀请语；保留全部/用户作品、分类、搜索以及推荐/最近更新/名称排序。详情包含头像、职业、性格、故事、喜好、世界、语气、作者及相处剧情，播放已发布的音色试听和演示视频（若发布数据包含视频）。模型与资源信息可以展开查看现有动作、背景、音色、音乐、提供方式及版本，再跳转到原有角色管理。

`GET /admin-api/v1/discovery?platform=ios` 读取与 App `/v1/store/characters` 相同的 `Store.Marketplace` 发布定义和公开角色查询，完整跟随全部分页，最多 10,000 个公开角色、15 秒。只有完整读取后返回 `complete=true`。原先角色管理中的私有、下架及历史条目不会混入发现名单。公开用户作品可继承公开来源角色的预览，私有草稿不显示。

当前推荐分类/顺序沿用 App 的 `MarketplaceCatalog.json`，显式复制到 `internal/admin/discovery_curation.json` 后独立打包；当前 16 个条目与客户端文件逐字相同。职业、故事、剧情、语音等来自实时发布数据，不建立另一份角色设定。分类附加规则与客户端一致：英语角色增加「英语」，恋爱/约会剧情增加「恋爱」，其他有剧情角色增加「剧情」，用户作品默认「日常」。内置角色的最近更新排序按 App 的 distantPast 规则处理，不把 OSS 发布时间当作客户端角色修改时间。后续调整客户端推荐分类时，发布者需同时更新这份公开元数据；运行服务不读取或链接客户端目录。

封面沿用 `CharacterArtworkLayout.frame` 的头部矩形与 0.94 卡片比例，避免简单居中裁剪截断耳朵、帽饰和脸部。图片通过已认证的同源 `GET /discovery/:id/media/:kind` 读取已发布 OSS 引用；只接受 cover/avatar/audition/video，限制公开未删除角色，不代理任意客户端网址。浏览页不自动播放、不调用 AI 或语音生成服务。管理页面展示公开内容；手机各账户的本地下载进度、订阅过滤和未同步本地作品属于设备/账户状态，不伪造为控制台状态。

## OSS 浏览

独立页面直接显示已配置的项目 Bucket：目录模式用官方 `ListObjectsV2` 的 `delimiter=/`、`CommonPrefixes`；全部对象模式递归列出当前路径前缀。支持路径输入、面包屑、根目录、上一级及前后分页，每页最多 50 项，保留官方 continuation token，不从文件名推导游标。页面只显示本页目录/文件数量和本页文件总大小，不把当前页伪装成 Bucket 全量统计。

选择文件读取 HEAD：对象路径、大小、更新时间、存储类型、Content-Type、ETag、用户元数据及 PostgreSQL 中的角色发布/发现预览引用。支持下载和按需预览已有图片、音频、视频、JSON、GLB/VRM/FBX；Unity 运行包只能下载检查。JSON 延续既有 1 MB 预览上限和敏感字段遮盖。文件读取透传 Range/Content-Range、Content-Length，支持媒体播放器。目录的零字节占位对象可查看；写入侧的资产路径规则保持原样。

沿用现有 owner 存储读取权限；发现公开内容供已登录管理员查看，Bucket 浏览仅 owner。列表或 HEAD 失败会明确提示，不显示空 Bucket 或虚构元数据。没有新增上传、删除、公开 ACL 或批量改变对象的流程，也没有修改 RAM 策略。

官方依据：[ListObjectsV2 的目录、前缀、编码与分页规则](https://help.aliyun.com/zh/oss/developer-reference/listobjectsv2/)、[Go SDK V2 列举对象](https://help.aliyun.com/en/oss/developer-reference/v2-list-objects)。编码由官方 SDK 处理，NextContinuationToken 含 `+` 等字符时使用 SDK 解码后的原值，再正常编码为下一次查询参数。

## 开发验证

前端 19 项单元测试、TypeScript/Vite 构建、Go vet/race 及四个 Go 程序构建通过。真实 Chrome 的明确本地夹具验收覆盖搜索、分类、创作者页、资料弹窗滚动与封面不覆盖文字、已有试听不自动播放、目录进入/返回、前缀、分页、HEAD/引用、下载链接、JSON 预览和 OSS 授权失败；桌面 1512×1050、手机 390×844，无页面错误及整体横向溢出。费用排行返回与原有费用页面同时完成浏览器回归。使用已有私有美术包，没有生成新图片，受限截图与测试结果在 `.local/discovery-oss-browser/`、`.local/discovery-billing-regression/`。

集成验证使用独立 PostgreSQL/Redis 测试实例和 `_test` 数据库，供应商边界为本地 OSS 官方 SDK 夹具，不访问付费模型。覆盖完整共享公开数据、排除私有/下架角色、公开作品继承预览、未知媒体不调用存储、平台校验、匿名 401、viewer 发现内容可读/Bucket 403、目录与含空格对象名称、特殊字符游标、HEAD 信息和签名读取。冷库上 API/Admin 两个测试包并发创建扩展曾产生迁移竞争，改为先用已有受锁保护的迁移命令初始化新库，再执行全套；测试种子名称、JSON 参数和 URL 编码夹具也在失败后修正，没有跳过失败检查。真实生产既有 OSS 列表已确认 200、50 项并有下一页，现有读取授权可用。
