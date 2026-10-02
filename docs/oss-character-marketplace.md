# 角色商店与 OSS 交付

发现页元数据由 PostgreSQL 提供，私有 OSS 保存不可变资源。App 不保存 AccessKey，不遍历 Bucket，也不通过 API 服务器转发大型模型。现阶段只发布用户授权的私人开发验证资源；这不代表获得模型的公开再分发许可。

## 分层

- `character_market_assets`：公开简介、模型描述、角色包定义、封面/头像/试听的对象定位与 SHA-256。公开 API 去掉对象键，只返回十五分钟有效的 GET 预签名 URL。
- `character_releases`：每个角色、版本、平台的不可变清单，记录下载字节数、SHA-256、兼容运行时与可交付状态。平台分为 `ios` 和 `ios-simulator`，禁止混用。
- 既有数据库与 AI worker：账号、订阅、作者、关系、记忆、会话、完整 AI 指令、语音供应商配置。角色包不含这些私有业务信息或密钥。
- OSS：`characters/{id}/previews/{sha256}/...` 是无需下载模型即可浏览的预览；`characters/{id}/releases/{version}/{platform}/{sha256}/character.zip` 是完整运行包。修改任何资源产生新版本，不覆盖旧对象。

运行包是标准 ZIP，一个角色、一个平台、一个版本对应一个文件。内部 `package.json` 声明每个成员大小和 SHA-256；`runtime/character.bundle` 包含 Unity 编译后的模型、原作控制器、曲线、材质、贴图、物理与背景；`media/` 包含音乐和三组首次问候；`metadata/`、`licenses/` 保存公开配置及署名。并非把原始 VRChat SDK/C#/DLL 发给用户执行。

## 接口

`GET /v1/store/characters?platform=ios&limit=200&after=...&q=...` 支持匿名浏览、游标和搜索；返回预览、资料、交付方式、当前平台版本与大小。只列出已发布商店元数据且角色仍公开的条目。

`POST /v1/characters/{id}/download?platform=ios` 使用现有可撤销 Bearer 会话、角色可访问性校验和限流，然后颁发十五分钟 GET 下载票据。未登录返回 401，私有/下架角色按现有访问规则处理。永久对象地址、AccessKeySecret 不交给 App。预签名 URL 自身是有效期内的读取凭证，不能把 URL 记入公开日志。

## 配置与权限收缩

密钥在服务器用户私有 `~/app/config/platform.env`，600 权限，独立于 Git 与版本化发布目录。使用官方 Go OSS SDK v2，`OSS_CREDENTIAL_SOURCE=env`、`OSS_ACCESS_KEY_ID`、`OSS_ACCESS_KEY_SECRET`、`OSS_REGION`、`OSS_BUCKET`、HTTPS `OSS_ENDPOINT`。生产可替换为 ECS RAM Role。

客户端分发只需要 `oss:GetObject`，资源限定 `acs:oss:*:*:starrynight-assets/characters/*`。生成签名本身不需额外写权限；实际 GET 必须被 RAM 授权。HeadObject 也使用读取权限。密钥改成只读后，发现、试听、下载照常；上传/删除管理能力会被 OSS 拒绝。以后使用独立发布凭证上传，运行服务只持有读取凭证。

## 发布与回滚

客户端 `scripts/package_character_delivery.py` 产出私有计划；此仓库 `cmd/asset-upload` 使用官方 SDK 执行上传及大小/哈希元数据验证，`-publish` 在一次数据库事务中登记平台清单与商店资料。同版本不同内容拒绝，同一计划可重试。先上传并验证，再发布，再删除 App 中对应的内置副本。保留本机原始包与私有恢复副本。

启动新服务前执行加法迁移 16，并沿用既有在线数据库备份与版本化部署流程。回滚代码不回滚业务数据库；角色包以版本选择回退，不在旧版本下覆盖文件。

官方依据：[OSS Go v2 预签名下载](https://www.alibabacloud.com/help/en/oss/developer-reference/v2-presign-download)、[Unity 分块压缩](https://docs.unity.com/en-us/engine/6000.0/script-reference/unityeditor/buildassetbundleoptions/chunkbasedcompression)。
