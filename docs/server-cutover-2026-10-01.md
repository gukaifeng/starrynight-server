# 正式云端切换与 Mac 旧服务清理

用户于 2026-10-01 明确授权从 Mac 旧部署切换至独立云端；采用云端已有的 21:51:04 +08:00 快照，不再同步其后 Mac 上的新写入，也不等待在途请求。此取舍由用户决定，不能把旧 Mac 数据误认为仍待自动合并的权威来源。

入口 `https://39.105.116.74:8443` 已从 standby 切至 active；旧 Mac Go API、Python AI、PostgreSQL、Redis 均停止，AI 自动启动项禁用。客户端 v0.84.0 / build 114 已安装至 iPhone 17，并验证 HTTPS、账户注册登录、账户认证的 AI 代理与角色语音状态查询。此次验证不发起百炼付费推理。2026-10-02 再次从 Mac 校验公网 `/health/ready` 返回 `ready`，`/health/ai` 返回 `ok`、协议 1、`paid_calls:false`。

用户随后要求删除 Mac 旧服务内容。客户端仓库已移除 `backend/`、`services/character_ai/` 及重复的服务端部署/安装脚本，源码改由本仓库维护。Mac 上的旧运行目录、旧共享连接配置和迁移快照按固定路径清理；客户端原始 VRChat 素材、已打包媒体、Unity/Xcode 工程和云端连接配置不在清理范围。客户端记录见 `../starrynight/docs/server-separation-2026-10-02.md`，客户端源码同步提交为 `0d120db`。

后续服务端变更在本仓库独立开发、验证和上线。`scripts/deploy/activate.py` 只用于 standby→active 的首次转换；当前生产已 active，不得重复运行它，也不能通过修改状态文件绕过保护。历史准备阶段、首次快照和部分验证依据见 [迁移记录](server-migration-2026-10-01.md) 与 [运行手册](runbook.md)。
