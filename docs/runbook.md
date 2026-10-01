# 独立服务端运行说明

## 本机开发和验证

在本仓库根执行 `make dev-up`，然后 `source .local/environment`。`make check` 执行 Go vet 和 race 单元测试；`make integration` 使用真实 PostgreSQL `starry_test` 和专用 Redis DB，测试多实例会话、数据隔离、版本冲突和并发写入。普通 `go test` 会跳过数据库集成测试，不能代替实际集成验证。

本仓库开发端口：API 18090、PG 55433、Redis 56380、AI 18766。`scripts/dev.sh` 的 PG 工具目录可以通过 `BACKEND_PG_BIN` 指定。私有状态在 `.local`；`make dev-down` 只管理本仓库实例。不要用旧仓库的 dev 脚本，也不要手动删除 `postmaster.pid`。

Python 环境按根 README 创建。单元测试不调用付费供应商。`STARRY_SEMANTIC_MODEL_CACHE` 可指向已准备好的模型目录，`STARRY_CHARACTER_CATALOG` 可指向客户端导出的角色能力 JSON；两者都是显式验证输入，不是运行依赖。

## 运行配置

| 变量 | 说明 |
| --- | --- |
| `STARRY_ENV` | development/test/production |
| `STARRY_LISTEN` | 程序默认 127.0.0.1:8090；本仓库 dev 配置覆盖为 18090 |
| `DATABASE_URL` | PG 连接；生产要求 sslmode=verify-full |
| `REDIS_URL` | Redis 连接；生产要求 rediss:// 并验证 CA |
| `REDIS_PREFIX` | 默认 starry:，测试使用隔离前缀 |
| `DB_POOL_SIZE` | 2..200，默认 16；当前小型云主机设为 8 |
| `ALLOW_TEST_GUEST` | 仅开发/测试；生产必须 false |
| `AI_UPSTREAM_URL`、`AI_SERVICE_TOKEN` | 同时设置；令牌只保存在服务端 |
| `STARRY_AI_CONFIG` | 私有 AI settings.json 路径 |
| `TEST_DATABASE_URL`、`TEST_REDIS_URL` | 专用测试存储，PG 名称必须以 _test 结尾 |

`make migrate` 或 `bin/starry-migrate` 是显式发布操作；API 启动不会自行迁移。会话仍存 Redis，需启用 AOF 和 noeviction。数据库或会话存储不可用时拒绝绕过认证。

`/health/live` 检查进程，`/health/ready` 检查 PG/Redis；`/metrics` 只在内部采集。AI 路由保留 SSE 立即刷新、WebSocket 升级及客户端取消；生产禁止游客、测试 inspector 和 AI 管理代理。完整账户合约在 `api/openapi.json`，流式协议仍由原 Python worker 实现。

## Linux 待切换部署

公网 TCP 8443 已配置 IP HTTPS；TCP 80 仅响应 ACME challenge。入口以 `scripts/deploy/Caddyfile.standby` 为准：健康探针放行，业务路径 503。`Caddyfile.active` 只是待正式切换的模板。

```sh
ssh starrynight
systemctl --user status starry-postgres starry-redis starry-ai starry-api starry-edge
systemctl --user list-timers starry-certificate-renew.timer
journalctl --user -u starry-api -u starry-ai --since '10 minutes ago'
readlink ~/starrynight-server/current
```

用户级 systemd 和 linger 管理启动/异常重启。版本切换修改 API/AI 的代码位置，数据与配置保留在 `~/app`，旧版本和升级前备份保留。`activate_standby_release.py` 验证清单、备份 PG、运行兼容迁移、重启云端 API/AI、检查健康；失败时恢复旧 unit 和代码链接。该脚本拒绝对非 standby 入口操作，不接管正式流量。

初次全新主机仍可用 `bootstrap_linux_user.sh` 与 `provision_linux.py`；后者仅允许空数据目录，严禁为了刷新数据删掉保护标记。现有服务器刷新要先备份目标，保持 standby，恢复经过验证的在线快照。

```sh
# 在 Mac 只读备份：源目录必须显式指定，不停止源服务
python3 scripts/deploy/snapshot_mac.py \
  --platform-environment /private/source-platform-environment \
  --ai-runtime '/private/source-ai-runtime' \
  --output .local/migration/snapshot-YYYYMMDD-HHMM
# 目标机校验恢复结果；仅创建并清理自己的两个验证账户，不调用付费 AI
python3 ~/starrynight-server/current/scripts/deploy/verify_linux.py \
  --snapshot ~/app/backups/snapshot-YYYYMMDD-HHMM
```

在线备份不是持续同步或跨库事务。正式切换前需要用户通知，暂停旧入口新增写入、等待在途请求结束，再做最终同步。旧体验身份与正式 UUID 账户保持原命名空间；更新客户端地址时要核对身份访问，不自动把旧消息归给新账户。细节见迁移记录。

## 维护工具和导出

所有付费脚本需要显式 `--allow-paid` 或 `--synthesize`；普通测试和部署不运行这些操作。`prepare_reply_novelty.py` 下载模型是人工准备步骤，自动测试不会调用它。

`generate_ai_performances.py --catalog /path/to/CharacterCatalog.json` 读取明确的能力导出；`generate_character_public_profiles.py` 默认导出 `.local/exports/CharacterPublicProfiles.json`；`prepare_character_openings.py` 使用 `authoring/` 文本，音频与客户端 JSON 输出到 `.local/exports/openings/`。已有音频和校验收据应从私有备份恢复，避免重新付费合成。

`install_character_ai_agent.py` 仅用于独立 Mac 开发，采用 `com.starrynight.server.character-ai`、`Application Support/StarryNightServer/CharacterAI` 与 18766，不操作旧 Mac 服务。本次云迁移无需运行它。
