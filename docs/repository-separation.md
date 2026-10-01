# 2026-10-01：服务端仓库拆分

用户要求所有服务端代码进入独立 `starrynight-server`，后续删除客户端仓库的旧副本；当前阶段保持旧 Mac 服务与客户端连接不变。用户随后明确要求删除新目录中未提交的替代实现，原样迁移已有服务端。

## 原实现和迁移范围

源仓库基线：`gukaifeng/starrynight` 的 `04d15b7de9af2c6e7fe32dec713790dbd1416e07`。原 `backend/` 提升为本仓库根，保留 chi/Huma、PG、Redis、Argon2id、SCS 和全部迁移。Go 源码仅替换 module/import 前缀；`services/character_ai` 的运行源码、JSON catalog 和精确依赖保持字节一致。未提交的 Gin/PG-session 替代实现已按用户要求删除，没有部署。

| 原位置 | 独立仓库位置/边界 |
| --- | --- |
| backend/{cmd,internal,migrations,api,go.mod,go.sum} | 根目录对应文件 |
| backend/deploy、backend/scripts/dev.sh | deploy/、scripts/dev.sh；独立开发端口 |
| services/character_ai | 同名路径，完整运行代码与测试 |
| scripts/deploy | 同名路径，另加可回滚版本部署工具 |
| scripts/{setup,start,install}_character_ai* | 同名工具，只写独立服务端状态，Mac label/端口独立 |
| scripts/prepare_reply_novelty、provision_character_voices、live_*smoke | 保留维护功能与显式付费保护；不自动调用 |
| scripts/generate_ai_performances | --catalog 接收能力 JSON，不再读取 iOS 源码树 |
| scripts/generate_character_public_profiles | 导出文件供客户端消费，不跨仓库写资源 |
| scripts/prepare_character_openings、assets/characters/openings.json | scripts/ 与 authoring/；只读配方、私有音频导出 |
| assets/characters/active-roster.json | authoring/active-roster.json，当前发布快照 |

构建和服务运行不需要客户端 checkout。单个角色能力契约测试改用显式 `STARRY_CHARACTER_CATALOG` 输入；模型语义检查使用已安装的私有模型输入。公开仓库不保存这些受限输入、生成音频、对话、音色 ID 或 Key。

## 客户端仓库后续清理

本次没有删除旧 `starrynight` 文件，没有停止/重启旧 Mac launchd、PG、Redis、账户 API 或 AI，也没有修改客户端 Connection 配置。

正式切换后，客户端仓库可删除旧 backend/、services/character_ai/、服务端维护/部署脚本。清理时要同步调整仍存在的客户端制作工具：`package_vrchat_library.py` 读取人物公开描述；`generate_host.py` 调用公开资料导出；角色能力、开场白和公开人物卡改为显式交换版本化 JSON/PCM。Unity/VRChat 转换、iOS 打包和客户端配置脚本仍属于客户端，不迁入服务端。

这些旧工具尚未改接新导出，是未来删除旧副本前的清理项；不会影响独立服务端构建或运行。服务端维护以后以本仓库为准，切换前源 Mac 的新增业务数据仍需最终同步。

## 运行位置

云端代码：`~/starrynight-server/releases/<版本>`，`current` 链接指向版本；Go 与 Python 从同一版本目录运行。私有运行资源：`~/app/{config,data,tls,venv,postgres,bin,backups}`。这样服务端代码不需要复制回客户端仓库，版本回滚也不会覆盖业务数据。

线上入口继续 standby；是否恢复业务入口、如何更新已有客户端、何时停 Mac，等待用户明确通知。

## 独立构建验证

2026-10-01 实际执行：`make check integration build` 通过，使用本仓库自己的 PG 55433 / Redis 56380；Go vet、race 和真实数据库集成均通过。2 API 副本 / 32 客户端 / 16 账户完成 320 次写入；这是 Mac 功能负载，不是云主机容量认证。

AI pytest 229 项通过、3 项模型用例起初跳过；显式指定已安装模型后，这 3 项另行通过（合计 232 项）。没有下载模型或调用付费供应商。现有 66 份开场 PCM 与收据校验通过，公开资料与能力导出逐字节匹配原制品；OpenAPI 重新生成后与原合约逐字节一致。Python 精确依赖安装及 `pip check` 通过。

源码比对：除 Go module/import 前缀外，所有 Go 业务代码与原 backend 一致；AI 运行代码、catalog 与锁定依赖保持字节一致。变化限于仓库组织、运维/作者工具路径、独立开发配置和显式测试输入。

独立项目重新取得只读在线快照：2026-10-01 **21:51:04 +08:00**，457 个文件，441 条消息、434 条请求、4,813 条使用记录；这仍是在线快照，正式切换前须最终同步。云端应用此快照与独立版本的结果另行记录。
