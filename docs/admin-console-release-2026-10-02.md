# 控制室交付记录 · 2026-10-02

## 关键变化

独立服务端仓库新增 React + Headless UI + Tailwind 管理前端，独立 Gin 管理 API、Goose 13 迁移和 Linux user-systemd 部署。使用 frontend-design 技能，雾蓝/月白与深蓝导航，真实服务状态星图，三栏数据工作区；窄屏改为抽屉，尊重系统减少动态设置。

覆盖现有 PG 业务表和 worker 的人格、提示词、状态、用量、声音与缓存。业务修改复用 CAS / 同步事件；内部账本只读。AI prompt 保存同步原模块引用，避免“检查页内容已改、实际生成仍用旧值”。运行配置原子写入私有覆盖文件，重启后仍生效。

## 问题处理与真实验证

- PostgreSQL Exec 模式不支持直接编码 map[string]string 审计目标；改成显式序列化 JSONB。真实数据库测试确认资料修改与同步事件同存。
- 重置后 PG 版本增长会挡住 worker 补偿；改为识别相同重置 UUID，允许继续确认 AI 清理。集成测试用 worker 503→200 覆盖真实部分成功与重试。
- 旧本机测试库不能用于此次迁移验证；使用新建 starry_admin14_test，真实 PG 17 与 Redis，没有用内存替身。
- 本机直接执行新产物收到 SIGKILL；通过 Go 临时构建路径启动管理进程完成实际浏览器验证，没有推断或声称已确认系统终止原因。
- 缓存的 Chrome 测试包缺 Framework，改用本机完整 Chrome。修复 dialog 外层高度为零、窄屏关闭按钮定位歧义和长列表/详情滚动；截图检查桌面与窄屏。
- make check / make integration / make build 全部通过；数据库集成覆盖全部资源列表、未登录、跨源、CSRF、只读角色、CAS 冲突、不可修改身份、Redis 多实例会话与撤销、官方目录、重置补偿和审计。Python 248 passed / 4 skipped；Vitest 2 passed。
- 浏览器访问真实 Go 管理进程与独立无付费 worker：登录、目录详情、AI 编辑、创建验证账户并编辑资料、确认弹窗取消、1512×1050 / 390×844 布局通过；page_errors=[]，付费调用 0。截图留 .local，不公开私有数据。

## 云端交付

- 生效发布：`20261002T071303Z-c20b993dd5c8`，源码 `c20b993dd5c8925399b88ef53627980ed8c44a89`，217 个文件经大小和 sha256 校验。Goose 13 已应用；PG 与在线 SQLite 备份在 `/home/starrynight/app/backups/before-api-20261002T071303Z-c20b993dd5c8`。
- 管理入口已部署到 `https://39.105.116.74:8444`。配置备份在 `/home/starrynight/app/backups/before-admin-20261002T071519Z`；独立 `starry-admin` 单元开机启动。首次 owner 凭证仅保存在部署机 `.local/admin-initial-login.md`，不写入仓库或验证输出。
- 公网真实浏览器登录、目录详情、AI 设定编辑表单、确认取消、桌面 1512×1050 和窄屏 390×844 全部通过，`page_errors=[]`。云端测试只查看，不创建账户、修改业务数据或调用付费供应商。
- 23 类 PG 资源与 15 类 AI 资源全部返回 200；owner 运维页面确认 API、AI、管理进程、Caddy、PG、Redis 六个单元 active。生产会话验证 Secure / HttpOnly / SameSite Strict 和 `__Host-` 前缀。
- 8444 页面与健康检查、原 App 8443 健康检查返回 200；未登录管理数据 401；App AI 路由继续要求账户鉴权（未登录 401），私有 worker 管理和 internal 路由为 404。没有通过放宽鉴权来做验证。
- 首次公网验证被本机 127.0.0.1:7897 代理中断，直连 curl 成功；增加可选 `ADMIN_TEST_DIRECT=true` 后真实 Chrome 和接口检查通过。另一次并行 Python 检查遇到本机 socket 错误，采用直连 curl 完成入口检查，保留失败日志，没有将失败当成成功。
- 私有验证结果与截图：`.local/admin-cloud-verification/`；客户端仓库没有加入管理平台实现。为验证启动的 Mac 隔离管理/worker/PG/Redis 进程在交付前停止；未恢复 Mac 旧业务服务。
