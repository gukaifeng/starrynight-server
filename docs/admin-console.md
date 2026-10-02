# 星夜控制室使用与维护

入口：`https://39.105.116.74:8444`。管理账号与 App 账号独立，App 的令牌无法取得管理权限。首次账号从 stdin 安全创建；登录资料只保存在部署者本机忽略目录，不在仓库中。

## 可以管理什么

| 范围 | 查看与操作 |
| --- | --- |
| 账户 | 新建密码账号、编辑完整个人资料、更换头像、强制所有设备退出、重置密码 |
| 设置与偏好 | 全局语言、主题、字体、称呼以及每角色偏好；CAS 保存并进入 App 同步流 |
| 内容 | 作者介绍、角色名称和公开设定、可见性、下架与恢复、新建官方元数据 |
| 订阅与关注 | 查看全部关系、新增或移除指定账户的关系 |
| 对话 | 归档消息、隐藏与置顶状态、人工记忆、共同片段、关系目标；明确确认后联动重置账户与 AI 上下文 |
| 模型资源 | 查看不可变清单、停止/启用下载；确认分发权、验证 OSS 文件大小和 sha256 元数据后发布新版本 |
| 反馈 | 查看工单，切换 open / in_progress / resolved / closed 状态 |
| AI | 编辑完整角色设定、场景、声线描述和全局提示词；恢复源设定；修改使用的模型、预算与预缓存参数 |
| 声音 | 查看音色任务、审核启用候选音色；额外确认后可生成候选音色（会调用付费模型） |
| AI 状态 | 上下文、自动记忆、情绪状态、请求、用量、动作记录、去重索引、场景和接话缓存；自动记忆可编辑/删除，缓存可按账户与角色清理 |
| 系统 | 会话、星夜号分配历史、同步游标、变更、重置收据、迁移版本、持久化音频数量与空间 |
| 维护 | 查看预列出的 systemd 单元和脱敏日志；重启 API / AI；管理员 owner / editor / viewer 权限与停用、密码重置、审计 |

同步时钟、重置收据、付款账本和审计不能任意改行，避免破坏账目或恢复已删除聊天。编辑归档消息不改写 AI 已经消费的推理上下文；需要两边清空时使用会话重置。

当前目录有 41 个角色元数据；AI worker 中有 11 份完整调教。管理台直接展示实际范围，不把本地预览角色冒充已开通的 AI。管理界面不会读取客户端的 Unity 源模型或自动上传受限模型资源。OSS 尚未配置时会明确拒绝发布，原有账号与 AI 使用仍正常。

AI 设置保存会影响后续调用，可能产生供应商费用；测试本控制室不调用付费供应商。角色恢复仅恢复 AI 源设定，不恢复历史聊天或原始模型文件。场景缓存清理保留已发消息的重播音频，已领取的场景生成不删除。

## 权限与审计

viewer 可查看数据；editor 可编辑常规业务数据；owner 才能维护管理员、凭证操作、资源发布、AI 参数和服务运行。至少保留一名启用的 owner。密码使用 Argon2id；会话存在独立 Redis 前缀、8 小时寿命和 30 分钟闲置过期。停用、改权限或重置管理密码递增 session_epoch，已有登录立即失效。

生产 cookie 为 `__Host-starry-admin`，Secure / HttpOnly / SameSite Strict。所有写入校验 Origin 与 CSRF token；登录通过 Redis 分布式限流。管理员操作记录目标 ID 和结果，不保存密码、供应商 Key 或正文副本。

写操作先写 started，之后写 completed / failed。进程在业务提交后崩溃时 started 可用于追查；这不是跨 PG 与 SQLite 的原子事务。重置用固定 UUID 收据重试，已完成的 PG 清理不会因其版本变化阻断 worker 补偿。

## 构建与独立部署

```
npm --prefix admin-web ci
npm --prefix admin-web test
npm --prefix admin-web run build
make check
make integration
make build
```

独立程序 `cmd/admin` / `bin/starry-admin` 绑定 127.0.0.1:8100。配置来自 platform.env 与私有 admin.env；前端是本发布目录的 admin-web/dist，账号表通过 Goose migration 13 创建。管理进程不服务 App 的 `/v1`，其接口在 `/admin-api/v1`。

使用 `scripts/deploy/build_release.py` 从干净的已提交源码打包。发布流程同时编译 API、管理进程和前端；部署机器无需 Node。新增 worker 管理模块须通过 active updater 的 `--restart-ai` 路径，先做 PG 与在线 SQLite 备份，再切换不可变发布链接。随后执行 `provision_admin.py --bootstrap`（密码 stdin），已存在管理员时不覆盖。

管理 provision 先备份 Caddy/unit/env，再校验 Caddy，启用管理进程并检查 readiness，最后添加独立 8444 监听并 reload。失败恢复原入口和 unit，不做数据回滚。后续普通发布也重启管理进程，使前端与 API 使用同一版本。Caddy 8443 的原始 App 路由保持不变。

维护：`systemctl --user status starry-admin`、`journalctl --user -u starry-admin`。首次密码可在管理员详情中重置自己；会使当前管理会话过期，需用新密码重新登录。供应商密钥、PG/Redis 连接和操作系统级配置继续由服务器私有配置维护，不提供任意命令或 SQL 控制台。

## 浏览器验证

`scripts/verify_admin_browser.mjs` 使用真实管理 API；设置 ADMIN_TEST_BASE、ADMIN_TEST_PASSWORD_FILE、CHROME_EXECUTABLE。默认仅查看；ADMIN_TEST_CREATE_FIXTURE=true 会创建独立验证账户并编辑资料，只在专用本地数据库使用。截图与结果写 .local/admin-verification。没有截图或浏览器通过记录时不可声称完成视觉验证。
