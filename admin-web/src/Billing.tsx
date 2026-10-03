import { useState } from "react";
import { Download } from "lucide-react";
import { Heading, Panel, State, Tabs, useData } from "./ConsoleUI";
import { BailianAnalysis } from "./BailianAnalysis";
import { modelInfo } from "./BillingAnalysis";
export { modelInfo } from "./BillingAnalysis";

type BillRow = Record<string, string>;
export type BillReport = {
  status: "ready" | "unavailable";
  month: string;
  product: string;
  view: string;
  bucket?: string;
  fetched_at: string;
  cached: boolean;
  rows: BillRow[];
  totals: BillRow[];
  next: string;
  total_count: number;
  error?: { code: string; message: string; request_id?: string };
  permissions: string[];
  complete?: boolean;
  granularity?: string;
  start_date?: string;
  end_date?: string;
};

export function months(now = new Date()) {
  const p = new Intl.DateTimeFormat("en", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit" }).formatToParts(now);
  const y = Number(p.find(v => v.type === "year")!.value), m = Number(p.find(v => v.type === "month")!.value);
  return Array.from({ length: 18 }, (_, i) => {
    const d = new Date(Date.UTC(y, m - 1 - i, 1));
    return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
  });
}

// Display the provider's decimal text without rounding tiny charges to zero.
export function money(value: string | undefined, currency: string) {
  return value === undefined || value === "" ? "—" : `${value} ${currency}`;
}

function Unavailable({ data }: { data: BillReport }) {
  const denied = /authoriz|forbidden|permission/i.test(data.error?.code || "");
  return <div className="billing-problem" role="status">
    <strong>{denied ? "需要账单读取权限" : "暂时无法读取账单"}</strong>
    <p>{data.error?.message}</p>
    {denied && <p>为当前阿里云凭据所属的 RAM 用户或角色附加这三个只读权限后，再刷新页面：</p>}
    {denied && <ul>{data.permissions.map(p => <li key={p}><code>{p}</code></li>)}</ul>}
    {data.error && <small>返回代码：{data.error.code}{data.error.request_id && ` · 请求 ID：${data.error.request_id}`}</small>}
  </div>;
}

function Updated({ data }: { data: BillReport }) {
  return <p className="billing-caption">查询时间：{new Date(data.fetched_at).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai" })}（北京时间）{data.cached ? " · 5 分钟内缓存" : ""}</p>;
}

function Summary({ product, month, refresh }: { product: string; month: string; refresh: number }) {
  const { data, error, loading } = useData<BillReport>(`/billing?month=${month}&product=${product}`, refresh);
  return <Panel title={product === "bailian" ? "百炼 · 账号费用" : "OSS · 账号费用"} className="billing-summary">
    <State loading={loading} error={error} />
    {data?.status === "unavailable" && <Unavailable data={data} />}
    {data?.status === "ready" && <>
      {data.totals.length === 0 ? <p className="billing-caption">所选月份暂无已出账记录。</p> : data.totals.map(total => <div className="billing-amounts" key={total.Currency}>
        <div><span>应付金额</span><strong>{money(total.PretaxAmount, total.Currency)}</strong></div>
        <dl>
          <div><dt>现金支付</dt><dd>{money(total.PaymentAmount, total.Currency)}</dd></div>
          <div><dt>代金券抵扣</dt><dd>{money(total.DeductedByCashCoupons, total.Currency)}</dd></div>
          <div><dt>未结清金额</dt><dd>{money(total.OutstandingAmount, total.Currency)}</dd></div>
        </dl>
      </div>)}
      <Updated data={data} />
    </>}
  </Panel>;
}

const csvFields = ["ProductName", "ProductDetail", "Currency", "BillingDate", "SplitBillingDate", "Region", "InstanceID", "SplitItemID", "BillingItem", "Usage", "UsageUnit", "ListPrice", "ListPriceUnit", "PretaxGrossAmount", "InvoiceDiscount", "AfterDiscountAmount", "DeductedByCashCoupons", "DeductedByResourcePackage", "PretaxAmount", "PaymentAmount", "OutstandingAmount"];
export function csv(rows: BillRow[]) {
  const cell = (v: string) => `"${(/^[=+\-@\t\r]/.test(v) ? "'" + v : v).replaceAll('"', '""')}"`;
  return "\uFEFF" + [csvFields, ...rows.map(r => csvFields.map(k => r[k] || ""))].map(row => row.map(cell).join(",")).join("\r\n");
}

function Details({ month, product, view, date, refresh }: { month: string; product: string; view: string; date: string; refresh: number }) {
  const [cursors, setCursors] = useState([""]), [page, setPage] = useState(0);
  const query = new URLSearchParams({ month, product, view, date, cursor: cursors[page] });
  const { data, error, loading } = useData<BillReport>("/billing?" + query, refresh);
  const rows = data?.rows || [];
  function download() {
    const url = URL.createObjectURL(new Blob([csv(rows)], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a"); a.href = url; a.download = `starrynight-${product}-${month}-${view}-page-${page + 1}.csv`; a.click(); URL.revokeObjectURL(url);
  }
  return <Panel title={view === "bucket" ? "项目 Bucket 分账明细" : "账号计费项明细"} action={<button className="secondary" onClick={download} disabled={loading || data?.status !== "ready" || !rows.length}><Download size={14} />导出本页 CSV</button>}>
    <State loading={loading} error={error} />
    {data?.status === "unavailable" && <Unavailable data={data} />}
    {data?.status === "ready" && <>
      {view === "bucket" && <p className="billing-caption">Bucket：{data.bucket}。仅显示该 Bucket 的分账记录。</p>}
      {rows.length === 0 ? <div className="state">所选条件暂无已出账记录。{view === "bucket" && "若尚未启用分账，请先在阿里云费用中心开通；开通后约 24 小时可查询。"}</div> : <div className="table-scroll"><table className="billing-table">
        <thead><tr><th>模型 / 资源</th><th>计费项 / 商品</th><th>地域 / 日期</th><th>用量 / 单价</th><th>原始金额</th><th>抵扣 / 优惠</th><th>应付金额</th><th>现金支付 / 未结清</th></tr></thead>
        <tbody>{rows.map((r, i) => {
          const model = product === "bailian" ? modelInfo(r.InstanceID) : null;
          return <tr key={i}>
            <td><strong>{model?.model || r.SplitItemName || r.SplitItemID || r.ProductDetail || r.ProductName || "—"}</strong>
              {model && <small>API Key ID：{model.key || "控制台调用"}<br />工作空间：{model.workspace}<br />{model.kind} · {model.channel}</small>}
              <details><summary>查看原始实例 ID</summary><code>{r.InstanceID || "—"}</code></details></td>
            <td>{r.BillingItem || "—"}<small>{r.ProductDetail || r.ProductName}<br />{({ Refund: "退款", Adjustment: "调账", SubscriptionOrder: "预付费", PayAsYouGoBill: "后付费" } as Record<string, string>)[r.Item] || r.Item}</small></td>
            <td>{r.Region || "—"}<small>{r.SplitBillingDate || r.BillingDate || month}</small></td>
            <td className="billing-number">{r.Usage === undefined ? "—" : `${r.Usage} ${r.UsageUnit || ""}`}<small>{r.ListPrice === undefined ? "—" : `${r.ListPrice} ${r.ListPriceUnit || ""}`}</small></td>
            <td className="billing-number">{money(r.PretaxGrossAmount, r.Currency)}</td>
            <td className="billing-number">{money(r.InvoiceDiscount, r.Currency)}<small>券：{money(r.DeductedByCashCoupons, r.Currency)}<br />资源包：{r.DeductedByResourcePackage || "—"}</small></td>
            <td className="billing-number billing-payable">{money(r.PretaxAmount, r.Currency)}</td>
            <td className="billing-number">{money(r.PaymentAmount, r.Currency)}<small>未结清：{money(r.OutstandingAmount, r.Currency)}</small></td>
          </tr>;
        })}</tbody>
      </table></div>}
      <div className="pagination"><span>第 {page + 1} 页 · 本页 {rows.length} 条 · 共 {data.total_count} 条</span><div><button className="secondary" disabled={page === 0 || loading} onClick={() => setPage(p => p - 1)}>上一页</button><button className="secondary" disabled={!data.next || loading} onClick={() => { setCursors(old => [...old.slice(0, page + 1), data.next]); setPage(p => p + 1); }}>下一页</button></div></div>
      <Updated data={data} />
    </>}
  </Panel>;
}

export function Billing({ refresh }: { refresh: number }) {
  const options = months();
  const [month, setMonth] = useState(options[0]), [product, setProduct] = useState("bailian"), [view, setView] = useState("details"), [date, setDate] = useState("");
  return <>
    <Heading title="云服务费用" description="查看阿里云已出账的百炼与 OSS 费用。金额直接来自官方账单。" />
    <div className="billing-controls"><label>账期月份<select aria-label="账期月份" value={month} onChange={e => { setMonth(e.target.value); setDate(""); if (options.indexOf(e.target.value) >= 12) setView("details"); }}>{options.map(m => <option key={m}>{m}</option>)}</select></label><span>北京时间 · 最近 18 个月</span></div>
    <div className="billing-summaries"><Summary product="bailian" month={month} refresh={refresh} /><Summary product="oss" month={month} refresh={refresh} /></div>
    <p className="billing-scope">上方汇总为当前阿里云账号的产品费用，可能包含其他项目。百炼明细中的 API Key ID 可用于核对调用来源；它与模型调用密钥不同。OSS 可切换到项目 Bucket 分账。</p>
    <Tabs items={[["bailian", "百炼"], ["oss", "OSS"]]} selected={product} onChange={p => { setProduct(p); setView("details"); setDate(""); }} />
    <div className="billing-controls">
      {product === "oss" && <label>费用范围<select aria-label="费用范围" value={view} onChange={e => setView(e.target.value)}><option value="details">账号全部 OSS 计费项</option><option value="bucket" disabled={options.indexOf(month) >= 12}>项目当前 Bucket 分账</option></select></label>}
      <label>按日查看（可选）<input aria-label="账单日期" type="date" min={month + "-01"} max={month + "-" + new Date(Number(month.slice(0, 4)), Number(month.slice(5)), 0).getDate()} value={date} onChange={e => setDate(e.target.value)} /></label>
      {date && <button className="secondary" onClick={() => setDate("")}>查看整月</button>}
    </div>
    {product === "bailian" ? <BailianAnalysis key={`${month}:${date}`} month={month} date={date} refresh={refresh} /> : <Details key={`${month}:${product}:${view}:${date}`} month={month} product={product} view={view} date={date} refresh={refresh} />}
    <Panel title="账单口径与更新时间"><div className="billing-notes">
      <p>普通账单约延迟 24 小时更新，实例信息约延迟 48 小时。Bucket 分账可能延迟 72 小时，且需先在费用中心启用分账。查询结果在服务端缓存 5 分钟。</p>
      <p>当月金额不包含尚未出账的费用；普通月账单在次月 3 日 12 点后可核对，分账在次月 4 日 12 点后可核对。现金支付、应付金额和未结清金额分别展示，退款与调账保留原始符号。不同币种分别计算。</p>
      <p>用量为阿里云计费项用量，不同单位不能相加。例如按小时出账的存储用量汇总并不等于当前占用空间。百炼统计覆盖所选范围全部明细，支持导出筛选明细或分组汇总；OSS CSV 仅导出当前页。模型信息支持官方六段格式及接口实际返回的缺少调用渠道的五段格式，原始实例 ID 始终保留；未提供的维度会单独列出。</p>
      <p><a href="https://help.aliyun.com/zh/user-center/developer-reference/api-bssopenapi-2017-12-14-describeinstancebill" target="_blank" rel="noreferrer">官方普通账单说明 ↗</a> · <a href="https://help.aliyun.com/zh/user-center/developer-reference/api-bssopenapi-2017-12-14-describesplititembill" target="_blank" rel="noreferrer">官方分账说明 ↗</a></p>
    </div></Panel>
  </>;
}
