# StarryNight Server · 星夜服务端

账户 API、AI 服务和部署工具的独立仓库。客户端位于另一个 `starrynight` 仓库；本项目构建、测试和运行不需要 iOS、Xcode、Unity 或角色二进制资源。

当前架构为 Go + Gin/Huma、PostgreSQL、Redis、Caddy 与独立 Python AI worker。2026-10-01 的迁移保留原实现；2026-10-02 按新的需求升级为 Gin，保留会话与对话协议，并增加账户安全、反馈及私有 OSS 下载授权。详见 [账户与内容交付设计](docs/design/account-and-assets-2026-10-02.md)。

| 目录 | 内容 |
| --- | --- |
| `cmd/`、`internal/` | Go 账户、资料同步、会话认证与 AI 代理 |
| `migrations/`、`api/` | PostgreSQL 迁移与 OpenAPI 合约 |
| `services/character_ai/` | 原 AI 编排、流式回复、ASR/TTS、音色、SQLite 与缓存 |
| `scripts/deploy/` | Linux 初始化、在线快照、数据校验、证书和版本部署 |
| `scripts/` | 独立开发、AI 配置、维护、资料导出和显式付费检查工具 |
| `authoring/` | 开场白文本、发布角色名册；不包含受限模型或音频 |
| `docs/` | 架构、运行说明、迁移记录与拆分边界 |

## 本地开发

需要 Go（版本约束见 `go.mod`）、PostgreSQL 17、Redis、Python 3.12+。Go 精确依赖在 `go.sum`，Python 锁定版本在 `services/character_ai/requirements.lock`。

```sh
make dev-up
source .local/environment
make check integration build
python3 -m venv .local/character-ai-venv
.local/character-ai-venv/bin/python -m pip install -r services/character_ai/requirements.lock
.local/character-ai-venv/bin/python -m pytest services/character_ai/tests -q
```

本仓库开发端口为账户 API **18090**、PG **55433**、Redis **56380**、私有 AI worker **18766**，只监听 loopback。生产端口由独立配置决定。开发脚本管理本目录的 `.local` 数据，保留原 Mac 部署的 8090/8766/55432/56379。

账户服务不需要启动 AI worker 即可测试。AI 单元测试使用 fake provider，不调用付费接口，不下载模型；本地语义模型测试需要显式设置 `STARRY_SEMANTIC_MODEL_CACHE`。客户端能力契约测试可设置 `STARRY_CHARACTER_CATALOG` 指向单独导出的 JSON。

新开发环境可用 `scripts/setup_character_ai.py --key-csv /private/key.csv` 创建私有配置，再执行 `bash scripts/start_character_ai.sh`。配置和状态留在 `.local/`，不写入客户端连接文件。迁移已有部署时直接保留既有私有配置和音色，不重新创建。

```sh
# 只停止本仓库新开的开发实例；不停止旧 Mac 部署
make dev-down
```

## 发布与切换

Linux 入口为 `https://39.105.116.74:8443`。80 仅用于 IP 证书验证与续期；数据库、Redis、AI worker 和 metrics 均不对公网开放。

**2026-10-01 已按用户明确通知完成正式切换。** 云端为 active，iPhone 17 已安装 0.84.0 / 114 并验证 HTTPS、注册、登录与 AI 认证代理；旧 Mac 服务与 AI 自动启动项已停止。云端使用 21:51:04 +08:00 快照，没有最终同步。见[正式切换记录](docs/server-cutover-2026-10-01.md)。

代码在 `~/starrynight-server/releases/<版本>/`，`current` 指向当前版本。私有配置、证书、数据、Python 环境和备份保持在 `~/app/`。以下版本部署脚本仅适用于 **standby**，当前 active 生产环境会拒绝执行；不要修改标记绕过保护。`activate.py` 是首次开放业务入口的工具，不是常规版本更新工具，不操作 Mac。

```sh
# 验证并提交源代码后创建带完整哈希清单的版本包
python3 scripts/deploy/build_release.py
# 上传到目标 ~/starrynight-server/releases/ 并解包，然后在目标执行：
python3 ~/starrynight-server/releases/<版本>/scripts/deploy/activate_standby_release.py \
  --release ~/starrynight-server/releases/<版本>
```

参见 [独立运行说明](docs/runbook.md)、[拆分与兼容边界](docs/repository-separation.md)、[迁移准备记录](docs/server-migration-2026-10-01.md)。准备期记录中的 standby / Mac 继续服务状态已由正式切换记录取代；云端私有备份继续保留；旧 Mac 服务和本地数据已按用户授权清理。

## 服务管理平台

独立管理入口为 **https://39.105.116.74:8444**，管理员与 App 用户隔离。管理台支持全部业务资源、AI 设定与运行数据，并提供资源及模型预览、声音试听与回收、会话撤销、备份恢复、配置应用、版本和证书维护。使用已有管理员登录；新环境首次 owner 通过专用 bootstrap 从 stdin 创建，不内置默认密码。

见 [控制室设计](docs/design/admin-console-2026-10-02.md)、[完整管理工作区](docs/design/admin-complete-management-2026-10-02.md)。前端代码在 `admin-web/`，服务及受限维护操作在 `internal/admin/` 与 `scripts/deploy/admin_ops.py`。镜像和部署版本均包含构建结果，运行时不需要 Node。
