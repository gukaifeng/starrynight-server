# 16 角色原作片段与开发动作资源发布

客户端 StarryNight 0.94.0 / 125 对当前 16 个角色完成原作片段审计，并增加 10 组开发者手动预览的身体/表情组合。源包版本 3.4.0，新增 required 能力 `core.source-motions@1`；原作 AI 审核表情选项不因独立预览而自动扩大。详细标准与源数量在客户端仓库的 `docs/character-standard/10-source-motion-library.md`、`docs/verification/source-motion-library/README.md`。

服务端无需代码、数据结构或部署进程变更，使用既有资产发布事务更新角色目录与不可变下载 release：

| 角色 | 平台 | Release | 包字节数 |
| --- | --- | ---: | ---: |
| anime-fiona | ios | 2 | 91,191,808 |
| anime-fiona | ios-simulator | 2 | 91,191,818 |
| anime-mizuki | ios | 2 | 132,629,906 |
| anime-mizuki | ios-simulator | 2 | 132,629,916 |
| anime-ramune | ios | 2 | 114,321,721 |
| anime-ramune | ios-simulator | 2 | 114,321,731 |

其他 13 角色随 App 内置更新。原作片段中含静态姿态、表情和显隐，不把库数量描述为连续肢体动画。图片、头像、音乐与试听音频复用已有资源，无图片、语音或对话生成调用。

## 发布过程与边界

- 本机 macOS Go 资产上传程序连帮助模式也被 SIGKILL，退出 137；未确认系统根因。改用现有 Linux `cmd/asset-upload` 在云端运行，不关闭系统安全程序。
- 发布计划由客户端离线构建显式导入，audience 为 `private-development`；源资源、计划与云端输入均不公开 Git。云端私有执行目录为 `~/app/authoring/source-motion-v094/`。
- 公网上传受到服务器网络带宽影响，终止该上传进程后使用同地域 OSS 内部 endpoint 续传。工具 HEAD 校验已存在对象，禁止覆盖不同内容。只修改该进程环境，生产服务仍使用公网 endpoint 生成客户端票据。
- 54 个对象的长度与 SHA-256 元数据全部核对后，发布工具在既有事务与发布锁下原子更新 16 个市场目录和 6 个平台 release。release 1 保留，未覆盖旧对象、清空用户资料或重置会话。
- 新 Bundle 含实际片段库、独立恢复组件与通用骨骼校准资产；仅更新 App 无法升级已下载旧 Bundle 的内容。

OSS 内网依据：[同地域 ECS 访问 OSS](https://www.alibabacloud.com/help/en/oss/user-guide/access-and-network-overview)。Bucket 仍为 private；无密钥、token、临时 URL、模型二进制或原作曲线进入公开仓库。

## 实际校验

公共 API 使用正常 TLS 验证：iOS 与 iOS Simulator 目录各返回 16 个角色，descriptor.packageVersion 都为 3.4.0；上述 6 个平台票据均为 release 2。全部未鉴权下载请求返回 401；同一私有合成账户获得的签名 URL 均支持 Range，返回 206 / 1,024 字节。API 不返回 OSS object_key。

客户端真实 Unity 模拟器 `CharacterDownloadUITests` 已通过：三个角色完成实际下载、会话加载、静态首句音频、普通旋转、源库数量与 10 个实验能力检查，分别运行开心和停止预览；重启并重新登录后恢复 Ramune，无需再次下载。测试禁用付费在线 AI。

这次只有资产元数据发布，未重启生产 API/AI 服务、未更改公开 HTTP 合约。既有服务端实现与当前部署保持独立。客户端安装到 iPhone 并成功启动；不将模拟器或 60/120 Hz 动画采样描述为真机 FPS 实测。
