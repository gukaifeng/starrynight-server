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

云端配置、发布及实际检查结果完成后追加。测试均不调用付费 AI 或生成图片。
