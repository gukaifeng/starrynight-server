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

云端发布与公网验证结果在部署完成后追加。客户端仓库没有加入管理平台实现。
