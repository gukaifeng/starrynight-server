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

这些旧工具尚未改接新导出，是未来删除旧副本前的清理项；不会影响独立服务端构建或运行。服务端维护以后以本仓库为准。按用户最新决定，切换时不再同步源 Mac 期间新增的数据。

## 运行位置

云端代码：`~/starrynight-server/releases/<版本>`，`current` 链接指向版本；Go 与 Python 从同一版本目录运行。私有运行资源：`~/app/{config,data,tls,venv,postgres,bin,backups}`。这样服务端代码不需要复制回客户端仓库，版本回滚也不会覆盖业务数据。

线上入口继续 standby；是否恢复业务入口、如何更新已有客户端、何时停 Mac，等待用户明确通知。

## 独立构建验证

2026-10-01 实际执行：`make check integration build` 通过，使用本仓库自己的 PG 55433 / Redis 56380；Go vet、race 和真实数据库集成均通过。2 API 副本 / 32 客户端 / 16 账户完成 320 次写入；这是 Mac 功能负载，不是云主机容量认证。

AI pytest 229 项通过、3 项模型用例起初跳过；显式指定已安装模型后，这 3 项另行通过（合计 232 项）。没有下载模型或调用付费供应商。现有 66 份开场 PCM 与收据校验通过，公开资料与能力导出逐字节匹配原制品；OpenAPI 重新生成后与原合约逐字节一致。Python 精确依赖安装及 `pip check` 通过。

源码比对：除 Go module/import 前缀外，所有 Go 业务代码与原 backend 一致；AI 运行代码、catalog 与锁定依赖保持字节一致。变化限于仓库组织、运维/作者工具路径、独立开发配置和显式测试输入。

独立项目重新取得只读在线快照：2026-10-01 **21:51:04 +08:00**，457 个文件，441 条消息、434 条请求、4,813 条使用记录；这仍是在线快照；用户随后决定切换时直接使用云端现有数据，不再最终同步。云端应用此快照与独立版本的结果另行记录。

## 云端完成验证：2026-10-01 22:02 +08:00

**独立仓库构建的服务已在 Linux 启动，数据已同步到 21:51:04 快照，公网仍处于 standby；等待用户明确通知再切换。**

- 实际运行版本 `20261001T135801Z-c8070f335d5f`，源码提交 `c8070f335d5fe8f7aa94e7d510ce3ace362eff4b`。API 与 AI 的 systemd WorkingDirectory 均为 `/home/starrynight/starrynight-server/current`，Go ExecStart 使用该版本的二进制。133 个发布文件的长度与 SHA-256 在目标核对通过。
- PG、Redis、AI、API、HTTPS 入口五个服务全部 active / enabled；证书续期 timer enabled。没有重启整台云主机，也没有操作原 Mac 进程。独立项目本机新建的测试 PG/Redis/API 已停止，测试数据保留。
- 新快照的 457 个文件校验通过，恢复后 452 个音频/音色/模型文件哈希一致。SQLite 18 张表完整性、行数以及逐行全内容排序哈希均与快照相同，包含 441 条消息、434 条请求、4,813 条使用记录。不是只比较文件名或消息条数。
- PG 15 张表按 UTC 归一比较数据；只允许已记录的兼容 migration 6。11 个角色、1 个官方作者、0 个正式用户。创建两个随机验证账户检查认证、隔离、409 冲突、AI 状态和管理/测试接口屏蔽后，两个账户均清理，用户数回到 0。11 个角色现有音色全部 approved，没有重新设计或合成。
- 新备份恢复先在独立 PG 候选库执行，再替换云端 standby；旧 PG 库 `starry_previous_20261001140037`、旧 AI/Redis 目录和配置位于 `~/app/backups/before-refresh-20261001140037`，原版本和升级前 PG 备份同时保留。业务入口全程没有开放。
- 公网 HTTPS `/health/ready` 与 `/health/ai` 均返回 200，curl TLS 验证为 0；业务 `/v1/capabilities` 按 standby 配置返回 503。80 可达，普通路径 404，仅用于证书 challenge。原 Mac 的 8090/8766 健康检查仍为 200，原 launchd AI 状态 running。
- 首次独立发布在备份预检阶段发现 `PGDATABASE` 环境变量不能直接承载完整连接 URI，尚未修改 cloud unit / current。已改为单独的 libpq 环境字段，保留 TLS 验证且不把密码放入命令行；Mac 专用测试 PG 和 Linux 实例均验证通过，随后完成发布。数据对比时 pg_dump 的循环外键提示只涉及 data-only 校验输出；实际备份和恢复使用完整 dump，恢复成功。

原始验证证据保存在本仓库 `.local/migration/`：`go-validation.log`、`python-tests.log`、`semantic-tests.log`、`activate-linux-final.log`、`refresh-linux.log`、`final-linux-verification.json`。云端也保留快照清单和恢复验证结果；不向公开 Git 提交私有日志或数据。

本轮没有调用付费模型、ASR、TTS 或生图，也未做切换后的 iPhone 真机端到端验收。原 Mac 仍可能接收新消息；用户随后明确允许直接切换，21:51:04 之后的数据不再补齐，也不等待在途请求完成。保留旧数据不等于双向持续复制。

## 用户更新切换策略：2026-10-01

用户原话：“你一会儿切换的时候，不需要管中间的数据了，直接暴力切换就行。”这取代先前关于暂停写入、等待在途请求和最终同步的要求。收到明确切换通知后，直接使用云端已恢复的数据开放业务并更新客户端连接，停用旧 Mac 服务；期间新增数据和未完成轮次不再迁移。旧数据库、配置和备份保留。本次只记录未来执行策略，没有开放云端业务入口、变更客户端连接或停止 Mac。
