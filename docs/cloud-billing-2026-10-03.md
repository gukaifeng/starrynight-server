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
