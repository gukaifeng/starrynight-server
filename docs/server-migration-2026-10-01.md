# 2026-10-01：Mac → 独立 Linux 服务器迁移

本文件保留首次 21:25 的部署证据。后续独立仓库发布和新快照结果见 [仓库拆分](repository-separation.md)；当前命令以 [runbook](runbook.md) 为准。

## 用户授权与切换边界

用户要求把项目服务迁到 `ssh starrynight`，先完成部署、启动与数据同步，再等待明确的切换通知。**本轮不得停止 Mac 服务或修改正在使用的客户端连接。** 原服务器仍是业务写入的权威来源。

新主机为 Ubuntu 26.04 / x86_64，2 个逻辑 CPU、约 1.6 GiB 内存；使用 `starrynight` 普通用户和 `/home/starrynight/app`。部署使用用户级 systemd，已启用 linger，使服务在登出后继续运行并随系统启动。没有获得或添加通用 sudo 权限，没有改动服务器上其他应用。

工作区还有其他人正在进行的 iOS、Unity 和 AI 开发。本轮只提交 `scripts/deploy/` 与本记录；运行源代码从 Mac 已部署的 `Application Support/StarryNight/CharacterAI/code` 复制，私有源码哈希清单保存在忽略目录及目标服务器。迁移期间原部署可能更新，交接时须再核对源版本。

## 端口、证书和访问

| 监听位置 | 端口 | 用途 |
| --- | --- | --- |
| 公网 | TCP 8443 | `https://39.105.116.74:8443`，统一 HTTPS 入口 |
| 公网 | TCP 80 | 仅 `/.well-known/acme-challenge/*`，证书签发和续期；其他路径 404 |
| loopback | 8090 | Go 账户 API |
| loopback | 8766 | 私有 Python AI worker |
| loopback | 55432 | PostgreSQL 17.11，要求 TLS |
| loopback | 56379 | Redis 8.10.2，仅 TLS |
| loopback | 2019 | Caddy 管理接口 |

用户已放行 8443 与 80，并以管理员身份为入口程序执行：

```sh
setcap cap_net_bind_service=+ep /home/starrynight/app/bin/caddy
```

不需要购买域名。使用 Let's Encrypt 的公网 IP 证书，Certbot 5.8.0 的 webroot 模式与 `shortlived` profile；IP 出现在证书 SAN 内。[IP 证书官方说明](https://letsencrypt.org/2026/01/15/6day-and-ip-general-availability)、[Certbot 官方操作说明](https://letsencrypt.org/2026/03/11/shorter-certs-certbot)。

`starry-certificate-renew.timer` 每 6 小时检查一次，并加入最多 15 分钟随机延迟；成功续期后 reload Caddy。采用 Ubuntu 仓库的 Caddy 2.6.2-14 包，程序位于用户目录；以后替换该二进制须重新设置 file capability。该 timer 只维护 TLS 证书，不执行 Git 同步或业务数据双向同步。

当前公网配置为 `Caddyfile.standby`：健康探针可访问，业务请求返回 503 和 `Retry-After: 300`。服务器上另有已校验的 `Caddyfile.active-prepared`，但未启用，避免新旧服务器同时接收写入。

## 运行环境和数据

Go API 为 Linux/amd64 静态构建。PostgreSQL 和 Redis 保持 Mac 使用的版本，在用户目录编译，并使用系统 OpenSSL；Go 以 production 模式运行，关闭测试游客。内部 PostgreSQL 使用 `sslmode=verify-full`，Redis 使用验证 CA 的 `rediss://`；没有跳过证书校验。AI 保留原 Key、client token、管理 token、已批准音色、语义模型与所有私有状态，关闭测试 inspector；管理接口不对公网代理。

私有配置、快照、轮次日志、依赖包和校验结果均在本机 `.local/server-migration/` 或新主机 `~/app/`，不进入公开 Git。服务迁移未上传 Unity 模型、角色源 ZIP、iOS 签名材料或 Mac 的 SSH 私钥。

在线快照由 `scripts/deploy/snapshot_mac.py` 产生：

1. SQLite Online Backup API 生成独立数据库，关闭备份连接后再生成清单，并执行 `integrity_check`。
2. 复制现有 audio、voices、models；展开模型缓存中的符号链接，避免复制后仍引用 Mac 路径。
3. `pg_dump -Fc` 导出账户数据库；`redis-cli --rdb` 获取 Redis 快照，不停止源服务。
4. 每个文件记录 SHA-256、大小和快照时间；传输后在 Linux 再校验。

第一份清单曾包含 SQLite 在连接关闭时自动消失的临时辅助文件。恢复前校验发现这个问题；脚本已改用显式关闭连接，并重新取快照。失败快照保留为诊断材料，没有用于初始化目标业务数据。

这些是独立存储的在线快照，**不是跨 PostgreSQL、Redis、SQLite 的全局事务，也不是持续复制**。Mac 在准备期间仍有新增消息；最终切换必须在获得通知后暂停旧入口写入、等待在途请求结束，再进行一次最终同步。不能将本轮快照描述为未来切换时的最终数据。

旧本机体验身份的 AI 历史保留原 owner 命名空间，不会被静默合并到新注册的平台账户。现有 App 的 `Connection.json` / `PlatformConnection.json` 仍指向原地址；切换时必须同时核对客户端入口与身份兼容，不能仅关闭 Mac 然后假定旧安装包自动改连公网。

## 运维与复跑

```sh
# 在 Mac：只读取源数据；每次使用新的私有目录
python3 scripts/deploy/snapshot_mac.py \
  --platform-environment /private/source-platform-environment \
  --ai-runtime /private/source-ai-runtime \
  --output .local/migration/snapshot-YYYYMMDD-HHMM

# 在新主机：以下初始化命令仅用于空目标，已有 PG_VERSION 时主动拒绝覆盖
bash ~/app/bootstrap_linux_user.sh
python3 ~/app/provision_linux.py --snapshot ~/app/backups/snapshot-YYYYMMDD-HHMM
python3 ~/app/verify_linux.py --snapshot ~/app/backups/snapshot-YYYYMMDD-HHMM

systemctl --user status starry-postgres starry-redis starry-ai starry-api starry-edge
systemctl --user list-timers starry-certificate-renew.timer
journalctl --user -u starry-api -u starry-ai --since '10 minutes ago'
```

`verify_linux.py` 将时间戳归一到 UTC 后，比较 PostgreSQL COPY 数据的行数与排序哈希、SQLite 每表行数和完整性、音频/音色/模型文件哈希。它通过正常 API 创建两个随机测试账户，验证隔离与乐观锁，然后仅删除自己创建的账户；不清空已有账户或 Redis，不调用付费供应商。

## 正式切换的执行顺序（尚未执行）

1. 收到用户明确的切换通知，并确认使用者结束会话；核对仍在更新的 Mac 部署代码与配置。
2. 准备兼容的客户端连接，明确旧体验身份与正式账户的访问方式；保存旧客户端配置。
3. 暂停旧入口的新写入并等待在途生成结束，制作最终 PG / Redis / SQLite 与媒体快照，校验后恢复到目标。保留现有目标快照和目录作为回滚点，不把初始化脚本强行用于已运行的目录。
4. 启用目标业务入口，验证真实客户端的登录、原会话归属与聊天/音频协议，然后完成客户端切换。
5. 验证新入口稳定后停用 Mac 的服务进程与自动启动项，保留原数据库和私有配置用于回滚。不得删除 Mac 原始数据。

一旦新服务器已经接收业务写入，回滚也必须先处理新产生的数据；不能无条件切回旧快照。

## 实际验证

北京时间 2026-10-01 21:25 验证：**服务器已部署并运行，处于等待用户通知的切换前状态；Mac 服务继续运行。**

- 数据基线为 `snapshot-20261001-2117`，清单内的真实完成时间是 **21:15:07 +08:00**（目录后缀仅为标识）。417 个文件在服务器验证 SHA-256 和大小通过；恢复后的 412 个媒体/模型文件再次验证通过，包含 375 个音频文件、13 个音色文件、24 个模型缓存文件。
- SQLite 完整性和所有表行数一致：414 条 messages、413 条 requests、13 条 voice_design_jobs、4,376 条 usage；11 个在册角色的音色状态均为 approved。语义模型在 Linux 本地加载与预热通过，没有重新设计音色、下载新权重或生成图片。
- 源 PostgreSQL 的正式用户数为 0，官方作者 1 个、角色 11 个；恢复后的业务数据一致。目标按仓库中的 `00006_conversation_reset.sql` 从版本 5 升到 6，新增空的会话重置表和一条 Goose 版本记录，没有修改原业务行。校验明确允许这一个兼容迁移，并保留原迁移记录。首次朴素哈希检查发现 `+08` / `+00` 的时间戳文本差异及新增版本记录，已按同一时间点和显式迁移规则重新核对通过，没有忽略业务差异。
- 新机器上通过正常 API 验证就绪、未认证拒绝、测试游客禁用、注册、两账户隔离、409 版本冲突、私有 AI 代理、测试 inspector 与管理路由不可访问。两个验证账户均通过正常注销接口清理，之后用户数恢复为 0。
- 实际重启了**新服务器上的** PG、Redis、AI、API 四个用户服务；API 在数据库启动期间经历一次启动失败，按配置 5 秒后自动重试并恢复。重启后四个服务、HTTPS 入口均 active，SQLite 仍为 414 条消息且完整性正常；Redis `appendonly=yes`。五个服务及证书 timer 均 enabled，linger=yes。没有重启整个云主机，也没有停止或重启 Mac 服务。
- 公网 `https://39.105.116.74:8443/health/ready` 返回 `{"status":"ready"}`；`/health/ai` 返回正常状态。curl 未使用 `-k`，TLS 验证结果为 0；根路径返回有意设置的 standby 503。其他内部应用端口仅监听 127.0.0.1。
- IP 证书由 Let's Encrypt YE1 签发，SAN 为目标 IP；首张证书到期为 **2026-10-08 12:05:27 +08:00**。`certbot renew --dry-run --run-deploy-hooks` 成功，包含入口 reload；续期 timer 已安装。
- Python 43 项锁定依赖已安装，`pip check` 通过。Go Linux/amd64 API 与迁移程序构建成功；Mac 上 `make test` 与连接真实 PG/Redis 的 `make integration` 通过。集成负载为两个实例、32 客户端、16 账户、320 次写入，仅代表本机功能验证，不是云服务器容量认证。
- 新服务器可通过正常 TLS 连接到现有供应商端点；只做未携带 Key 的 HEAD 请求，收到 HTTP 404。**没有发送真实推理、ASR、TTS 或图像生成请求**，因此本轮不声称完成付费供应商响应和 iPhone 真机端到端验收。

原始证据留在 `.local/server-migration/`：`verify-linux.json`、`backend-test.log`、`backend-integration.log`、快照清单，以及新服务器 `~/app/logs/`。公开记录不包含密码、供应商 Key、会话令牌、聊天正文或音色源数据。
