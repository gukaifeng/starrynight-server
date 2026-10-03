# 0.96 加法动画修复资源发布

客户端 StarryNight 0.96.0 / 127 修复 Generic 骨骼曲线直接用于 Additive 层、空状态重复叠加参考旋转的问题。当前 Hikarun、Koharu、Ramune 存在原作加法图；前两者随 App 内置，Ramune 必须同步更新可下载 Bundle。为统一构建与验收，三项 OSS 角色的两个平台均发布新不可变 release 3，保留 release 1/2。

| 角色 | 平台 | Release | 包字节数 |
| --- | --- | ---: | ---: |
| anime-fiona | ios | 3 | 91,198,493 |
| anime-fiona | ios-simulator | 3 | 91,198,503 |
| anime-mizuki | ios | 3 | 132,546,206 |
| anime-mizuki | ios-simulator | 3 | 132,546,216 |
| anime-ramune | ios | 3 | 114,372,399 |
| anime-ramune | ios-simulator | 3 | 114,372,409 |

客户端与服务器角色包合约、数据库和 API/AI 运行进程未变更；目录 descriptor 仍为包标准 3.4.0，release 版本负责区分运行资产的实际字节。封面、头像与声音复用既有资源，没有调用 AI 生成接口。

## 发布与验证

- 显式的私有构建输入位于云端 `~/app/authoring/conversation-pose-v096/`。上传途中 SSH 中断，使用 rsync 续传，随后由现有官方 OSS SDK 发布工具检查文件长度和 SHA-256，未用文件大小检查替代最终内容校验。
- `cmd/asset-upload` 默认模式上传不存在的对象并验证；`-publish` 模式只验证已上传对象并发布目录。因此先运行默认模式，再运行 `-publish`。最初直接运行发布模式因新对象不存在而拒绝发布，既有 release 2 保持有效。修正执行顺序后，两步均成功。
- 发布过程使用同地域 OSS 内部 endpoint，限发布进程。生产仍签发公网下载链接；Bucket 私有，密钥和签名链接不进入公开仓库。
- 同一计划包含 54 项对象、16 项商店目录和 6 项平台 release。既有发布事务与锁完整执行后，正常 TLS 验证的公共商店 API 在 ios / ios-simulator 平台均返回 16 角色，Fiona、Mizuki、Ramune 的 `release_version` 均为 3。
- 用户的账户、聊天、记忆和订阅未重置，旧资产对象未覆盖或删除，没有重启生产服务。

客户端新增本地角色资源管理：删除下载包先等待 Unity 解除加载和引用，确认后移除本机目录，不调用服务端会话删除接口。实现与姿态检查见[客户端验收记录](https://github.com/gukaifeng/starrynight/blob/main/docs/verification/conversation-pose-resources-v096/README.md)。

原始模型、转换曲线、ZIP、上传计划、账户凭证与实际角色截图均留在私有目录；此仓库只记录发布方法与脱敏结果。
