# 百炼与 OSS 费用详情

管理入口为 `https://39.105.116.74:8444/#billing`，左侧常用工具「云服务费用」。只有 owner 可以查询，沿用可撤销管理会话；App 用户与普通管理查看者不能读取费用。所有代码在独立服务端仓库，客户端无需修改。

## 官方接口与范围

- `QueryBillOverview`：按账期和产品查询账号汇总，分别展示应付、现金支付、代金券抵扣、未结清金额。
- `DescribeInstanceBill`：按月或指定日查询计费项明细，单次 100 条、NextToken 分页；模型推理实例 ID 符合官方六段格式时展示模型、工作空间和 API Key ID。保留原始实例 ID，其他格式不猜测。
- `DescribeSplitItemBill`：以当前配置的 OSS Bucket 为 SplitItemID 查询项目分账；需要在费用中心开通分账。普通 OSS 明细不能准确分配到各 Bucket。

账号汇总可能含同账号其他项目，页面明确标注该范围；不能从 `sk-…` 模型调用密钥推断账单中的 API Key ID，不能把整个账号的费用声称为星夜独占成本。Bucket 分账单独展示，不和账号总账混算。不同币种分别汇总，金额按十进制处理、保留小额费用与退款符号。CSV 导出仅包含当前页，并防止文本字段触发电子表格公式。

普通账单支持最近 18 个月、约延迟 24 小时；实例属性约延迟 48 小时，当月最终账单次月 3 日 12 点后可核对。分账支持最近 12 个月，分拆项可延迟 72 小时，最终账单次月 4 日 12 点后可核对。未出账费用不包含在结果中，用量是计费周期汇总而非实时存储占用。

## 凭据与只读策略

现有百炼 API Key 只用于模型调用，不能认证 BSS。账单进程优先使用私有环境变量 `BILLING_ACCESS_KEY_ID`、`BILLING_ACCESS_KEY_SECRET`、可选 `BILLING_SECURITY_TOKEN`；未配置时复用现有 OSS 官方凭据提供器。ECS Role 支持自动刷新，独立 Role 可设置 `BILLING_CREDENTIAL_SOURCE=ecs`。百炼产品代码默认 `sfm`，可通过 `BILLING_BAILIAN_PRODUCT_CODE` 适配实际账单商品。所有真实值保留在服务器私有环境文件，不提交 Git、不交给网页。

将 [账单只读策略](billing-readonly-policy.json) 附加给所选 AccessKey 所属 RAM 用户或角色。只允许 `bss:DescribeBillList`、`bssapi:DescribeInstanceBill`、`bssapi:DescribeSplitItemBill`，不开放充值、下单、续费或退款操作。API Action 与 RAM Action 名称不完全一致，不能直接把接口名当授权名。

服务端仅调用官方 HTTPS BSS Endpoint 与三个读取接口，使用官方 RPC 签名和既有 OSS SDK 的凭据提供器。固定 Endpoint、不跟随重定向、15 秒超时、请求取消透传、错误信息不包含签名地址或供应商原始消息。仅转发明确允许的账单字段。成功结果在 Redis 缓存 5 分钟；失败不缓存，授权后刷新即可重试。权限不足、无配置与成功空账单分别处理，不能把失败显示成零费用。

## 验证

2026-10-03：云端现有 OSS AccessKey 调用官方 `QueryBillOverview` 返回 HTTP 400 / `NotAuthorized`，因此真实费用尚待 RAM 授权，不能声称已读到实际账单。页面仍可完成部署并展示具体授权要求。

Go vet / race 单元测试、前端 9 项单元测试、TypeScript / Vite 生产构建和全部 Go 程序构建通过。真实 PostgreSQL / Redis 的 API 与管理集成测试共 25 项通过，覆盖匿名 401、viewer 403、owner 查询、Redis 缓存、分页、Bucket 筛选、精确金额与权限失败处理。供应商 HTTP 边界使用明确测试夹具，没有调用付费模型。

旧共享测试库在迁移 12 时报注册序列不存在；保留该库，改用本次新建的 `starry_billing_20261003_test`，从头执行完整迁移后通过。没有调整生产迁移或修改已有序列来绕过问题。

真实 Chrome 的本地明确夹具验收通过：1512×1050 与 390×844、计费明细、小额金额、退款、分页、CSV、Bucket 页面与授权提示，无页面错误、无整体横向溢出。截图和测试结果在忽略目录 `.local/billing-browser/`。这属于界面验收，不代表已获得阿里云真实费用。

官方依据：[账单 API 概览](https://help.aliyun.com/zh/user-center/developer-reference/api-overview-1)、[账单汇总及授权](https://help.aliyun.com/zh/user-center/developer-reference/api-bssopenapi-2017-12-14-querybilloverview)、[实例账单](https://help.aliyun.com/zh/user-center/developer-reference/api-bssopenapi-2017-12-14-describeinstancebill)、[Bucket 分账](https://help.aliyun.com/zh/user-center/developer-reference/api-bssopenapi-2017-12-14-describesplititembill)、[百炼账单字段](https://help.aliyun.com/zh/model-studio/bill-query-and-cost-management)、[RPC 签名规则](https://help.aliyun.com/en/cmn/developer-reference/signature-mechanism)。

## 云端发布与只读验收

运行版本 `20261003T040355Z-452cd59031a3`，实现提交 `452cd59031a3a872c5e6e6d21e405111282f9e87`。发布清单 297 个文件，经现有 active updater 的 check-only 校验后上线。PG 备份保留于 `~/app/backups/before-api-20261003T040355Z-452cd59031a3`；没有新增数据库迁移，也没有修改公开 App API 或角色、AI 源码。AI 进程 PID 和启动时间在发布前后完全一致。

公网实际验收：App 8443 和管理 8444 readiness 均为 200，API / Admin / AI / Caddy 均 active；匿名费用请求 401。真实主管理员会话查询百炼汇总、OSS 汇总、百炼明细、当前 Bucket 分账，管理接口均返回 200 的明确 unavailable 状态及阿里云 `NotAuthorized`，没有返回虚假的金额。当前 Bucket 配置已正确用于分账请求。

真实 Chrome 公网验收通过登录、费用与 Bucket 页面、刷新、1512×1050 和 390×844，无页面错误或整体横向溢出。此前 Node 独立 APIRequestContext 遇到本机连接 EBADF；改为页面内 fetch，使用与用户相同的浏览器网络路径后完成匿名认证校验。未修改 TLS 校验或略过匿名检查。原始结果及截图在 `.local/billing-production/`，不公开提交。

上述是初次发布时的权限状态；随后完成了以下授权后验收。

## RAM 授权后真实账单验收

用户为既有 OSS AccessKey 所属 RAM 用户添加 `AliyunBSSReadOnlyAccess` 后，2026-10-03 公网只读验收确认权限已经生效。该系统策略是账号费用读取策略，当前明确包含 `bss:Describe*`、`bssapi:Describe*`、`bssapi:Query*` 以及百炼 `modelstudio:ListBilling*`、`modelstudio:GetBilling*`，因此同一身份也可以读取百炼账单，并非只允许查看这个 RAM 用户或原 OSS Bucket 自己产生的费用。控制台路径为 RAM → 身份管理 → 用户 → 目标用户新增授权 → 账号级别 → 系统策略。也可继续使用本仓库仅三个操作的自定义策略；两者不必重复添加。依据：[系统策略内容](https://help.aliyun.com/zh/ram/developer-reference/aliyunbssreadonlyaccess)、[RAM 用户授权](https://help.aliyun.com/zh/ram/user-guide/grant-permissions-to-the-ram-user)。

真实主管理员会话的接口结果：

| 账期 | 产品与范围 | 状态 | 返回条数 |
| --- | --- | --- | --- |
| 2026-10 | 百炼账号汇总 | ready | 3 |
| 2026-10 | OSS 账号汇总 | ready | 1 |
| 2026-10 | 百炼计费明细 | ready | 18，无后续分页 |
| 2026-10 | 当前项目 Bucket 分账 | ready | 0 |
| 2026-09 | 百炼账号汇总 | ready | 3 |
| 2026-09 | OSS 账号汇总 | ready | 0 |

百炼默认产品代码 `sfm` 已与实际返回的「大模型服务平台百炼」匹配。账号汇总已返回官方真实金额；不在公开仓库记录账号财务数值、API Key ID 或 Bucket 名称。本月金额尚未最终结算，也不能声称是星夜专属费用。Bucket 查询成功且过滤已配置，但空结果不能证明项目费用为零，也不能据此证明分账数据已经开始生成；该部分仍需核对控制台分账启用状态及出账延迟。

真实 Chrome 再次通过公网登录、匿名 401、费用及 Bucket 页面、1512×1050 和 390×844 检查，无页面错误或整体横向溢出。截图、结果与受限财务响应保留于忽略目录 `.local/billing-after-grant/`。本次仅查询和记录验证结果，没有修改客户端、云端运行代码或云资源配置，也没有调用付费模型。

## 百炼多维分析

百炼标签页提供完整账单分析，OSS 保持原有分页及 Bucket 分账。统计与筛选只读，沿用 owner 权限；不需要新增阿里云权限。账号月汇总与筛选后统计分别标注范围，不能将账号费用直接称为星夜专属费用。

- 15 个分组维度：模型、API Key ID、工作空间、输入/输出类型、调用渠道、地域、商品/服务、计费项、账单类型、付费方式、实例标签、财务单元、资源组、免费额度用完即停标识、账单日期。可选择一级及二级分组，并按应付金额、计费明细条数或名称排序。
- 模型、Key、商品是常用筛选，其余在「更多筛选维度」展开；支持组合筛选、原始字段搜索和币种筛选。费用排行、按日图与分组表可点击筛选；筛选同步更新全部面板和计费明细。
- 费用面板显示应付、原始金额、优惠、代金券、现金支付、未结清，并单列正向费用和负向调整/退款；排行占比按同币种正向费用计算，不用含退款的净额做分母。
- 用量按输入/输出类型及单位分别求和，Token、千tokens、秒、张等不互相转换或混加。明细条数不是模型调用次数；账单不能直接推导调用次数。缺失有效金额不补零，缺少单位的用量不汇总。
- 「整月汇总」完整读取月计费项，适合快速分类；「按日展开」逐日调用官方 DAILY 接口，当前月只到北京时间当天，并显示每日已出账费用。也可沿用顶部具体日期只统计某日。MONTHLY 返回的记录不伪造逐日日期。
- 分组 CSV 导出当前条件下全部分组，明细 CSV 导出当前条件下全部记录，不受界面分页影响；继续处理 CSV 公式转义，真实原始实例 ID 可供核对。

新增管理接口 `GET /admin-api/v1/billing/analysis?month=YYYY-MM&granularity=monthly|daily&date=YYYY-MM-DD`。接口完整跟随每页 NextToken，成功才返回 `status=ready` 和 `complete=true`，并返回实际范围 `start_date`/`end_date`。上游失败、重复游标、总条数变化或最终条数不一致均丢弃部分结果，不能发布部分金额；失败不缓存。每次最多 100 个供应商查询、10,000 条记录、60 秒，超出时明确建议按具体日期查询。成功的月/日结果在 Redis 缓存 5 分钟，逐日长查询失败后可复用已经完成的日期。进程内供应商请求间隔至少 150 毫秒，低于官方该接口 10 次/秒的账号限制；其他进程仍需共享账号时自行遵守总限额。

模型维度优先按官方六段推理 ID 解析；真实账单中的部分语音、图片、翻译等记录为省略调用渠道的五段结构。兼容仅限 `key;llm-/ws-工作空间;模型;计量类型;0/1标识`，缺少渠道保持「未提供」。这是实际接口返回的兼容处理，不宣称官方文档保证该五段格式。训练 ID 只解析官方三段结构中的工作空间，不推断模型；其他未知结构全部保留并列入未知维度。依据：[官方推理与训练字段](https://help.aliyun.com/zh/model-studio/bill-query-and-cost-management)、[分页、DAILY 日期及限流](https://help.aliyun.com/zh/user-center/developer-reference/api-bssopenapi-2017-12-14-describeinstancebill)。

金额在浏览器中使用 BigInt 与十进制字符串精确累计，支持科学计数及小额费用；Number 只用于图表几何比例，不用于金额累计、排序和导出。币种始终分开，原始财务数据不提交公开仓库。

实现验证：Go vet / race 检查和四个 Go 可执行程序构建通过；前端 15 项单元测试及 TypeScript/Vite 构建通过。专用全新 `_test` 数据库及真实 Redis 的 API/Admin 集成测试 32 项通过，包括完整跨页统计、逐日范围、缓存、权限、重复游标、条数变化、第二页授权失败及失败不缓存。复用旧测试库曾遇到已有商城主键残留，改用新库；首次新库命名未满足测试要求的 `_test` 后缀，修正后完成全套，不跳过失败检查。真实 Chrome 的明确本地夹具覆盖 112 条账单、两级分组、模型筛选、明细分页、导出全部 72 条筛选记录、每日趋势筛选、退款及权限失败；桌面 1512×1050、手机 390×844 无页面错误和整体横向溢出，明细表内部滚动。验证文件在忽略目录 `.local/billing-analytics-browser/` 和 `.local/billing-analytics-integration-fresh.log`。

### 多维分析上线验收

实现提交 `10ffb0f73e5166d82f41eb7e67e1c91e5a221028` 已推送 main。运行版本 `20261003T060148Z-4e4cf7c4d333`，运行源码提交 `4e4cf7c4d33308e88a08acbae866ab6742c81695` 在 `billing-analytics-runtime` 分支：基于此前实际运行的 `452cd59`，仅取本次 16 个已验证的账单相关文件。其 cmd/internal/migrations/admin-web/go.mod/go.sum 与 main 完全一致；services 与之前生产版本完全一致。该分支也已推送，可复建。这样不会在仅升级费用功能时顺带发布 main 中尚未上线的其他 worker 测试或入口维护改动，也没有修改既有 updater 的校验规则。

发布清单 303 个文件，通过原 active updater 的 check-only、文件校验及 worker 一致性校验后上线。PG 备份 `~/app/backups/before-api-20261003T060148Z-4e4cf7c4d333`；没有新增迁移。API/Admin 更新后 readiness 均 200，API/Admin/AI/Caddy 均 active。AI PID 633686、启动时间 2026-10-03 06:34:57 CST 与发布前相同，没有重启 AI；原入口与 TLS 配置保持原状。

公网真实 Chrome 验收：分析接口匿名 401；主管理员查询 2026-10 月汇总成功，完整 18 条，实际模型选择器识别 7 个模型。页面筛选费用累计与官方明细的服务端精确汇总相同；实际切换模型和二级 Key 分组，导出整月全部记录及筛选后分组 CSV。按日查询成功，范围 2026-10-01 至 2026-10-03，共 37 条带日期明细，`complete=true`。月与日是不同聚合颗粒度，条数不应相等。桌面和手机宽度检查均无浏览器错误、无整体横向溢出。

截图、真实 CSV、受限接口响应和验证结果保留在 `.local/billing-analytics-production/`，不提交公开仓库。月费明细、每日累计可能因出账和取整方式存在差异，最终核对仍遵循官方账期结算时间与统计范围。
