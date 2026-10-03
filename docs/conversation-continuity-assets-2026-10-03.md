# 0.97 连续性与手臂适配资源发布

客户端 StarryNight 0.97.0 / 128 修复人形动画采样后的 FX 遮罩、会话表情和动作的切换/恢复连续性，并增加独立标记的有限手臂惯性适配。全部 16 个角色共用生成器和运行组件；13 个随 App 内置，Fiona、Mizuki、Ramune 的 iOS / iOS Simulator 资源同步发布为不可变 release 4。保留 release 1/2/3，不覆盖旧对象。

| 角色 | 平台 | Release | 包字节数 |
| --- | --- | ---: | ---: |
| anime-fiona | ios | 4 | 91,216,843 |
| anime-fiona | ios-simulator | 4 | 91,216,853 |
| anime-mizuki | ios | 4 | 132,556,062 |
| anime-mizuki | ios-simulator | 4 | 132,556,072 |
| anime-ramune | ios | 4 | 114,356,503 |
| anime-ramune | ios-simulator | 4 | 114,356,513 |

## 发布与兼容

- 私有输入由客户端显式打包，传入云端 `~/app/authoring/conversation-continuity-v097/`，使用现有官方 OSS SDK 发布器。先上传和验证，再以 `-publish` 在既有事务与发布锁内写入市场目录。
- 54 个对象均通过长度及 SHA-256 元数据验证，16 项目录和 6 项平台 release 发布成功。正常 TLS 验证的 `/v1/store/characters` 在两个平台均返回 16 个角色；三项可下载角色的 `release_version` 全部为 4。
- 同地域 OSS 内部 endpoint 仅用于发布进程；生产继续签发公网预签名下载链接。发布脚本只读取云端既有环境配置，不复制或输出凭证。
- 包标准保持 3.4.0，运行版本仍为 `starry-runtime/1`；本次追加 Unity 指令 CPU 耗时回执，旧接收方可忽略该字段。用户账户、对话、记忆和订阅没有重置，没有重启生产 API、AI、数据库或缓存。
- 封面、头像、音乐、音色和预制开场全部复用，不调用付费生成接口；角色 ZIP 与源模型不提交公开 Git。

## 静音诊断回归

服务端已有 `voice_trace.source` 在没有音频事件时也会保存并返回生成与表演规划快照。本次新增 `test_muted_reply_keeps_generation_and_performance_timing`，用隔离测试存储及异步模拟任务验证无音频流的文字标记、规划跨度、最终快照和持久化一致；不调用 AI 提供商。

`PYTHONPATH=. .local/character-ai-venv/bin/pytest services/character_ai/tests/test_voice_trace.py -q`：4 项通过。首次省略 `PYTHONPATH` 时收集失败，补正后通过。服务端只增加回归测试和发布记录，不为这次客户端展示改动重启服务。

客户端完整适配根因、60/120 Hz 数值检查、实际 Unity 播放器及下载验证见[客户端验收记录](https://github.com/gukaifeng/starrynight/blob/main/docs/verification/continuity-timing-v097/README.md)。原始报告、上传计划、账户配置和截图继续保留在私有目录。
