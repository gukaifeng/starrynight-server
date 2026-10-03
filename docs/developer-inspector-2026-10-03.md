# 开发账号只读 AI 设定检查

## 故障原因

客户端开发构建中存在 AI 设定检查入口，但迁云时 Go 网关在 production 禁止测试 inspector，worker 的 `enable_test_inspector` 也关闭。因此正常会话可用，并不表示这个检查入口可用；旧客户端统一显示“请确认测试 AI 服务已连接”，没有说明是权限拒绝。

这次保留生产环境的通用测试限制，为明确配置的开发账号单独开放已有只读端点。不是切回 development，不开放游客、管理员代理、OpenAPI、其他测试路由，也不信任 App 自报的“开发版”标志。

## 两层授权与数据隔离

- Go 配置 `AI_INSPECTOR_ACCOUNT_IDS` 为以逗号分隔的固定账户 UUID。配置验证拒绝通配符、无效 UUID、零 UUID 和非规范格式。只有现有 SCS 会话解析出的账号在此列表中，才允许 POST `/v1/ai/testing/characters/{id}/inspector`。
- 网关从会话覆盖 `X-Starry-Account` 和 `X-Starry-Installation`，继续校验角色可见性，使用只在服务端保存的服务令牌访问内网 worker。客户端伪造同名请求头不会得到别人的权限。
- Worker 私有 `ai-settings.json` 的 `developer_inspector_accounts` 配置同一批账号 UUID。worker 的持久化 owner 是服务令牌与 `UUID|UUID` 的 HMAC，检查和请求记录使用这一实际命名空间进行授权，不拿原 UUID 当作数据库 owner。
- 保持全局 `enable_test_inspector:false`。普通生产账号返回 404，未登录返回 401。只允许已授权开发账号记录未来的实际请求、内部复核与分段编排；原来没有记录的请求不补造。
- 检查报告保留完整角色设定、提示词、上下文、记忆、实际请求、预缓存分支和执行规则源码，排除认证令牌、API 密钥等凭证。各分区 ID 与内容独立。
- Inspector 不执行付费生成。网关读取目标快照时不再为这个只读 POST 创建初始关系目标，避免检查本身修改账户状态。

## 配置与撤销

由运营者在服务器私有 `~/app/config/platform.env` 设置 `AI_INSPECTOR_ACCOUNT_IDS=<账号 UUID>`；在 `~/app/config/ai-settings.json` 设置 `developer_inspector_accounts:["<同一 UUID>"]`。正式 UUID 可从受控管理平台按星夜号查询，不使用昵称作鉴权，也不在 App 内写死管理员账号。

备份私有配置后修改，两边都配置完成再重启 `starry-api` 与 `starry-ai`。撤销时从两边列表移除该 UUID 并重启；SCS 登录、普通对话与管理员账户不受影响。配置文件和含用户设定的验收报告只留在私有目录，不提交公开仓库。

未来正式客户端继续通过 `STARRY_TEST_TOOLS` 编译开关移除检查页面。服务器上的列表是独立授权机制，即便有人重新编译客户端也不能凭客户端开关取得权限。

## 验证

- 完整 Python：285 passed、4 skipped。新增用真实 worker owner 派生规则测试授权开发账号读取、普通账号拒绝、无认证拒绝、报告分区不同、检查不写数据和请求记录只针对已授权 owner。
- Go race 测试与全部程序构建通过。配置与路由测试验证默认关闭、指定账号开放、非法路径/方法仍拒绝。
- 真实 PostgreSQL/Redis 集成通过。新增生产模式下的完整 Gin/SCS→worker 验证：授权账号 200，普通账号伪造开发账号头仍为 404，未登录为 401；只读检查前后关系目标版本不变。
- 复用先前测试数据库第一次运行遇到旧 marketplace fixture 主键残留。没有清除旧库，改用新建独立 `settings_inspector_test` 数据库完成全部集成测试。测试结束后停止临时本机服务。

测试均不调用付费 AI 或生成图片。

## 云端发布与实际验收

源码提交 `ffcf235f20e4ca5d8b100d5a5c9d824a5564cf54`，发布 `20261002T223022Z-ffcf235f20e4`。升级器更新 API 与 AI，重启后 ready。私有配置修改前备份，原子写入并保持 0600 权限；仅将主开发账号 `xy100000001` 对应的固定 UUID 加入两边列表，全局 `enable_test_inspector` 保持 false。账户 UUID、密钥和完整用户报告不进入公开记录。

实际通过 worker 的原有认证与账户 owner 派生链路检查 16 个发布角色：chiffon、fiona、hikarun、ichigo、koharu、lime、mafuyu、meiyun、milfy、mao、mizuki、perula、plum、ramune、shinano、sio。全部返回 200，每个报告 50 个独立分区。逐一验证角色 ID、分区 ID 唯一、persona/prompts/context 内容不同，且包含请求、记忆、预缓存、灵动接话与语音执行规则；报告不包含实际服务令牌或 API 密钥。请求均为只读检查，没有调用生成模型。

云端普通 owner 仍返回 404，公开 Go 网关匿名请求返回 401。授权登录账号经过公开网关的行为由真实 Gin/SCS/PostgreSQL/Redis 集成覆盖；本轮没有复制主用户的客户端会话令牌执行云端外部请求，也没有将 worker 验收写成手机页面验收。客户端真实 Unity 模拟器检查导航、本机降级可读性已通过；手机更新安装成功，远程启动被锁屏保护拒绝。

发布包首次解压时误形成同名嵌套目录，check-only 因找不到部署脚本失败。修正解压目标后 check-only 通过；仅在确认重复目录内 source_commit 等于本次发布提交后删除本次创建的重复目录，没有动已有发布或用户数据。

升级前程序备份位于服务器私有 `~/app/backups/before-api-20261002T223022Z-ffcf235f20e4`，配置备份位于同一私有 backups 根目录下的 `developer-inspector-*`。无需数据库迁移。源码与测试可公开，带用户设定的完整响应、配置与认证资料只留私有路径。

## 公网入口修复（0.98 客户端阶段）

用户确认实际账号为 `xy100000001`。只读核对发现 API 配置、运行进程与 worker 配置均已授权；真正的遗漏是 Caddy 的 `/v1/ai/testing/*` 整段拦截，已授权请求仍在边缘返回 404。

新增精确的 POST `/v1/ai/testing/characters/[a-zA-Z0-9_-]+/inspector` 转发，保留 Gin 的可撤销登录会话、固定 UUID allowlist、角色访问检查，以及 worker 的 owner/HMAC 授权。其他 testing、admin、internal 路由仍直接拒绝；没有打开全局测试权限。`scripts/deploy/enable_inspector_edge.py` 对现有配置做窄范围、幂等更新，先验证 Caddy，再原子替换与 reload，失败恢复；保留管理平台其他站点。

云端已执行该修复。公网未登录 POST 现返回 401（此前入口直接 404）；对应账号的 worker 只读检查覆盖全部 16 个角色，均返回 200，每个报告 48 个不同分区 ID。没有生成对话、语音或图片，也没有复制客户端认证令牌。Go API/config 测试与部署脚本 2 个边缘规则测试通过。这是分层验证；未把手机上的实际登录请求描述为已验证。私有结果在服务器 `~/app/authoring/inspector-v098/grants.json`，不提交完整用户资料。
