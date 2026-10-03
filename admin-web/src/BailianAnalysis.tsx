import { useEffect, useMemo, useState } from "react";
import { Download, Filter, X } from "lucide-react";
import { Panel, State, useData } from "./ConsoleUI";
import type { BillReport } from "./Billing";
import {
  aggregate,
  compareDecimal,
  csvTable,
  dimensions,
  dimensionValue,
  filterRows,
  groupedCSV,
  modelInfo,
  percent,
  valueLabel,
  type Aggregate,
  type BillRow,
  type Dimension,
  type Filters,
} from "./BillingAnalysis";

const amountLabels = [
  ["PretaxAmount", "应付金额"],
  ["PretaxGrossAmount", "原始金额"],
  ["InvoiceDiscount", "优惠金额"],
  ["DeductedByCashCoupons", "代金券抵扣"],
  ["PaymentAmount", "现金支付"],
  ["OutstandingAmount", "未结清金额"],
] as const;
const primaryFilters: Dimension[] = ["model", "key", "product"];
const advancedFilters: Dimension[] = [
  "workspace",
  "kind",
  "channel",
  "region",
  "item",
  "billType",
  "subscription",
  "tag",
  "costUnit",
  "resourceGroup",
  "quota",
  "date",
];
const labelOf = (d: Dimension) => dimensions.find(([key]) => key === d)![1];
const formatMoney = (v?: string, currency = "CNY") =>
  v === undefined ? "—" : `${v} ${currency}`;
function saveCSV(content: string, name: string) {
  const url = URL.createObjectURL(
    new Blob([content], { type: "text/csv;charset=utf-8" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function rowName(g: Aggregate, keys: Dimension[]) {
  return g.values.map((value, i) => valueLabel(keys[i], value)).join(" / ");
}
function Usage({ values }: { values: BillRow }) {
  return Object.keys(values).length ? (
    <>
      {Object.entries(values).map(([unit, value]) => (
        <small key={unit}>
          {value} {unit}
        </small>
      ))}
    </>
  ) : (
    <small>无可汇总用量</small>
  );
}

function CostBars({
  groups,
  keys,
  totals,
  onSelect,
}: {
  groups: Aggregate[];
  keys: Dimension[];
  totals: Aggregate[];
  onSelect: (g: Aggregate, keys: Dimension[]) => void;
}) {
  return (
    <Panel title="费用排行" className="billing-ranking">
      <p className="billing-caption">
        按正向应付费用排序 · 点击查看该组 · 负向调整与退款单列
      </p>
      {!groups.length ? (
        <div className="state">当前筛选没有费用记录。</div>
      ) : (
        totals.map((total) => (
          <div key={total.currency} className="billing-bars">
            <span className="billing-currency">{total.currency}</span>
            {groups
              .filter((g) => g.currency === total.currency)
              .sort((a, b) => compareDecimal(b.positive, a.positive))
              .slice(0, 10)
              .map((g, i) => {
                const share = percent(g.positive, total.positive);
                return (
                  <button
                    className="billing-bar"
                    key={JSON.stringify([g.values, g.currency])}
                    onClick={() => onSelect(g, keys)}
                    aria-label={`查看分组 ${rowName(g, keys)} ${g.currency}`}
                  >
                    <span className="billing-bar-rank">{i + 1}</span>
                    <span className="billing-bar-content">
                      <span>{rowName(g, keys)}</span>
                      <span className="billing-bar-track">
                        <span style={{ width: `${share}%` }} />
                      </span>
                    </span>
                    <span className="billing-bar-amount">
                      {formatMoney(g.missingAmount === g.count ? undefined : g.positive, g.currency)}
                      <small>
                        {share.toFixed(2)}%
                        {g.refund !== "0" && ` · 负向 ${g.refund}`}
                      </small>
                    </span>
                  </button>
                );
              })}
          </div>
        ))
      )}
      {groups.length > 10 && (
        <p className="billing-caption">
          每个币种显示前 10 组，全部 {groups.length} 组见下方汇总表。
        </p>
      )}
    </Panel>
  );
}

function DailyTrend({
  rows,
  onSelect,
}: {
  rows: BillRow[];
  onSelect: (g: Aggregate, keys: Dimension[]) => void;
}) {
  const days = aggregate(rows, ["date"]);
  const currencies = [...new Set(days.map((d) => d.currency))];
  return (
    <Panel title="按日费用趋势" className="billing-trend">
      <p className="billing-caption">
        点击日期筛选 · 仅绘制已出账记录 · 不同币种分别展示
      </p>
      {!days.length && <div className="state">所选范围暂无已出账记录。</div>}
      {currencies.map((currency) => {
        const data = days
          .filter((d) => d.currency === currency)
          .sort((a, b) => a.values[0].localeCompare(b.values[0]));
        const abs = (s: string) => (s.startsWith("-") ? s.slice(1) : s);
        const max = data.reduce(
          (v, d) =>
            compareDecimal(abs(d.amounts.PretaxAmount || "0"), v) > 0
              ? abs(d.amounts.PretaxAmount || "0")
              : v,
          "0",
        );
        return (
          <div className="billing-day-series" key={currency}>
            <span className="billing-caption">{currency}</span>
            <div className="billing-days">
              {data.map((g) => {
                const value = g.amounts.PretaxAmount,
                  negative = value?.startsWith("-");
                return (
                  <button
                    className={`billing-day ${negative ? "negative" : ""}`}
                    key={g.values[0]}
                    onClick={() => onSelect(g, ["date"])}
                    title={`${g.values[0]}：${formatMoney(value, currency)}`}
                    aria-label={`筛选日期 ${g.values[0]} ${currency}`}
                  >
                    <span className="billing-day-value">{value ?? "—"}</span>
                    <span className="billing-day-track">
                      <span
                        style={{
                          height: `${percent(abs(value || "0"), max)}%`,
                        }}
                      />
                    </span>
                    <span>{g.values[0].slice(5)}</span>
                  </button>
                );
              })}
            </div>
          </div>
        );
      })}
    </Panel>
  );
}

export function BailianAnalysis({
  month,
  date,
  refresh,
}: {
  month: string;
  date: string;
  refresh: number;
}) {
  const [grain, setGrain] = useState("monthly"),
    [filters, setFilters] = useState<Filters>({}),
    [search, setSearch] = useState("");
  const [primary, setPrimary] = useState<Dimension>("model"),
    [secondary, setSecondary] = useState<Dimension | "">("");
  const [order, setOrder] = useState("amount-desc"),
    [groupPage, setGroupPage] = useState(0),
    [detailPage, setDetailPage] = useState(0);
  const query = new URLSearchParams({
    month,
    date,
    granularity: date ? "daily" : grain,
  });
  const { data, error, loading } = useData<BillReport>(
    "/billing/analysis?" + query,
    refresh,
  );
  useEffect(() => {
    setGroupPage(0);
    setDetailPage(0);
  }, [data]);
  const ready = data?.status === "ready" && data.complete === true;
  const all = ready ? data.rows : [];
  const rows = useMemo(
    () => filterRows(all, filters, search),
    [all, filters, search],
  );
  const keys =
    secondary && secondary !== primary ? [primary, secondary] : [primary];
  const totals = aggregate(rows);
  const groups = aggregate(rows, keys).sort(
    (a, b) =>
      a.currency.localeCompare(b.currency) ||
      (order === "name"
        ? rowName(a, keys).localeCompare(rowName(b, keys))
        : order === "count"
          ? b.count - a.count
          : compareDecimal(
              a.amounts.PretaxAmount || "0",
              b.amounts.PretaxAmount || "0",
            ) * (order === "amount-asc" ? 1 : -1)),
  );
  const currencies = [...new Set(all.map((r) => r.Currency))].sort();
  const visibleGroups = groups.slice(groupPage * 25, (groupPage + 1) * 25),
    visibleRows = rows.slice(detailPage * 50, (detailPage + 1) * 50);
  const active = Object.entries(filters).filter(([, v]) => v);
  const resetPages = () => {
    setGroupPage(0);
    setDetailPage(0);
  };
  function setFilter(key: Dimension | "currency", value: string) {
    setFilters((old) => ({ ...old, [key]: value }));
    resetPages();
  }
  function selectGroup(g: Aggregate, selected: Dimension[]) {
    setFilters((old) => ({
      ...old,
      currency: g.currency,
      ...Object.fromEntries(selected.map((k, i) => [k, g.values[i]])),
    }));
    resetPages();
  }
  function clear() {
    setFilters({});
    setSearch("");
    resetPages();
  }
  function select(d: Dimension) {
    const values = [...new Set(all.map((r) => dimensionValue(r, d)))].sort();
    return (
      <label key={d}>
        {labelOf(d)}
        <select
          aria-label={`筛选${labelOf(d)}`}
          value={filters[d] || ""}
          onChange={(e) => setFilter(d, e.target.value)}
          disabled={!ready}
        >
          <option value="">全部（{values.length} 类）</option>
          {values.map((v) => (
            <option key={v} value={v}>
              {valueLabel(d, v)}
            </option>
          ))}
        </select>
      </label>
    );
  }
  const badgeCounts = ["model", "key", "workspace"].map(
    (d) =>
      new Set(
        rows
          .map((r) => dimensionValue(r, d as Dimension))
          .filter((v) => !["未提供", "未提供 API Key ID"].includes(v)),
      ).size,
  );
  const missing = totals.reduce((n, t) => n + t.missingAmount, 0);
  function downloadDetails() {
    const fields = [
      "Currency",
      "BillingDate",
      "ProductDetail",
      "BillingItem",
      "Region",
      "InstanceID",
      "Item",
      "SubscriptionType",
      "Usage",
      "UsageUnit",
      "ListPrice",
      "ListPriceUnit",
      ...amountLabels.map(([f]) => f),
      "DeductedByResourcePackage",
      "Tag",
      "CostUnit",
      "ResourceGroup",
    ];
    saveCSV(
      csvTable(
        [...dimensions.map(([, label]) => label), ...fields],
        rows.map((r) => [
          ...dimensions.map(([d]) => dimensionValue(r, d)),
          ...fields.map((f) => r[f] || ""),
        ]),
      ),
      `starrynight-bailian-${month}-filtered.csv`,
    );
  }
  return (
    <div className="billing-analysis">
      <Panel
        title="百炼账单分析"
        action={
          <span className="billing-complete">
            {ready
              ? `完整读取 ${all.length} 条`
              : loading
                ? "正在读取完整账单"
                : "统计未完成"}
          </span>
        }
      >
        <div className="billing-analysis-controls">
          <div className="billing-filter-grid">
            <label>
              统计颗粒度
              <select
                aria-label="统计颗粒度"
                value={date ? "daily" : grain}
                disabled={Boolean(date) || loading}
                onChange={(e) => {
                  setGrain(e.target.value);
                  clear();
                }}
              >
                <option value="monthly">整月汇总 · 快速读取</option>
                <option value="daily">按日展开 · 含每日趋势</option>
              </select>
            </label>
            {primaryFilters.map(select)}
            <label>
              币种
              <select
                aria-label="筛选币种"
                value={filters.currency || ""}
                onChange={(e) => setFilter("currency", e.target.value)}
                disabled={!ready}
              >
                <option value="">全部币种（分别统计）</option>
                {currencies.map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </select>
            </label>
            <label>
              搜索账单
              <input
                aria-label="搜索账单"
                placeholder="模型、实例 ID、商品、标签…"
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  resetPages();
                }}
                disabled={!ready}
              />
            </label>
          </div>
          <details className="billing-advanced">
            <summary>
              <Filter size={14} />
              更多筛选维度
            </summary>
            <div className="billing-filter-grid">
              {advancedFilters.map(select)}
            </div>
          </details>
          {active.length > 0 || search ? (
            <div className="billing-filter-chips">
              {active.map(([key, value]) => (
                <button
                  key={key}
                  onClick={() => setFilter(key as Dimension | "currency", "")}
                  aria-label={`移除${key === "currency" ? "币种" : labelOf(key as Dimension)}筛选`}
                >
                  {key === "currency" ? "币种" : labelOf(key as Dimension)}：
                  {key === "currency"
                    ? value
                    : valueLabel(key as Dimension, value!)}
                  <X size={12} />
                </button>
              ))}
              <button onClick={clear}>清除全部筛选</button>
            </div>
          ) : null}
        </div>
        <State loading={loading} error={error} />
        {loading && (
          <p className="billing-caption">
            统计会读取所选范围的全部分页；按日展开需逐日查询。切换账期会取消当前请求。
          </p>
        )}
        {data && !ready && !loading && (
          <div className="billing-problem" role="status">
            <strong>完整统计暂不可用</strong>
            <p>{data.error?.message || "账单尚未完整读取，请刷新重试。"}</p>
            {data.error?.code && <small>返回代码：{data.error.code}</small>}
          </div>
        )}
        {ready && (
          <p className="billing-analysis-status" role="status">
            {date ||
              (data.granularity === "daily"
                ? `${data.start_date} 至 ${data.end_date}`
                : `${month} 整月`)}{" "}
            · 已完整读取 {all.length} 条 · 筛选后 {rows.length} 条 ·{" "}
            {groups.length} 个分组 · {badgeCounts[0]} 个已识别模型 /{" "}
            {badgeCounts[1]} 个 API Key / {badgeCounts[2]} 个工作空间
            <br />
            <small>
              账单计费项条数不代表模型调用次数。查询时间：
              {new Date(data.fetched_at).toLocaleString("zh-CN", {
                timeZone: "Asia/Shanghai",
              })}
              {data.cached ? " · 5 分钟内缓存" : ""}
            </small>
          </p>
        )}
      </Panel>
      {ready && (
        <>
          <Panel title="当前筛选 · 费用统计" className="billing-statistics">
            {!rows.length && (
              <div className="state">
                当前条件没有已出账明细。请调整筛选条件。
              </div>
            )}
            {totals.map((total) => (
              <div className="billing-ledger" key={total.currency}>
                <span className="billing-currency">{total.currency}</span>
                <div className="billing-stat-grid">
                  {amountLabels.map(([field, label]) => (
                    <div
                      key={field}
                      className={field === "PretaxAmount" ? "payable" : ""}
                    >
                      <span>{label}</span>
                      <strong>{total.amounts[field] ?? "—"}</strong>
                    </div>
                  ))}
                </div>
                <p className="billing-caption">
                  正向费用：{formatMoney(total.positive, total.currency)} ·
                  负向调整 / 退款：{formatMoney(total.refund, total.currency)}
                </p>
              </div>
            ))}
            {missing > 0 && (
              <p className="billing-caption">
                {missing}{" "}
                条明细缺少有效应付金额，未计入金额汇总；对应记录仍保留在明细中。
              </p>
            )}
          </Panel>
          <Panel title="分组方式" className="billing-group-controls">
            <div className="billing-filter-grid">
              <label>
                一级分组
                <select
                  aria-label="一级分组"
                  value={primary}
                  onChange={(e) => {
                    setPrimary(e.target.value as Dimension);
                    if (e.target.value === secondary) setSecondary("");
                    setGroupPage(0);
                  }}
                >
                  {dimensions.map(([d, label]) => (
                    <option key={d} value={d}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                二级分组
                <select
                  aria-label="二级分组"
                  value={secondary}
                  onChange={(e) => {
                    setSecondary(e.target.value as Dimension | "");
                    setGroupPage(0);
                  }}
                >
                  <option value="">不分组</option>
                  {dimensions
                    .filter(([d]) => d !== primary)
                    .map(([d, label]) => (
                      <option key={d} value={d}>
                        {label}
                      </option>
                    ))}
                </select>
              </label>
              <label>
                分组排序
                <select
                  aria-label="分组排序"
                  value={order}
                  onChange={(e) => {
                    setOrder(e.target.value);
                    setGroupPage(0);
                  }}
                >
                  <option value="amount-desc">应付金额从高到低</option>
                  <option value="amount-asc">应付金额从低到高</option>
                  <option value="count">计费明细条数</option>
                  <option value="name">分组名称</option>
                </select>
              </label>
            </div>
          </Panel>
          <div className="billing-chart-grid">
            <CostBars
              groups={groups}
              keys={keys}
              totals={totals}
              onSelect={selectGroup}
            />
            <Panel title="计费用量构成" className="billing-usage">
              <p className="billing-caption">
                按输入 / 输出类型和单位汇总 · 用量来自官方计费项
              </p>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>输入 / 输出类型</th>
                      <th>币种</th>
                      <th>用量</th>
                      <th>应付金额</th>
                    </tr>
                  </thead>
                  <tbody>
                    {aggregate(rows, ["kind"]).map((g) => (
                      <tr key={JSON.stringify([g.values, g.currency])}>
                        <td>{g.values[0]}</td>
                        <td>{g.currency}</td>
                        <td className="billing-number">
                          <Usage values={g.usage} />
                        </td>
                        <td className="billing-number">
                          {g.amounts.PretaxAmount ?? "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {!rows.length && <div className="state">暂无可汇总用量。</div>}
            </Panel>
          </div>
          {data.granularity === "daily" ? (
            <DailyTrend rows={rows} onSelect={selectGroup} />
          ) : (
            <p className="billing-daily-hint">
              查看每天的费用变化：将统计颗粒度切换为「按日展开」。月汇总记录没有逐日日期，不会被当作每日数据。
            </p>
          )}
          <Panel
            title="分组汇总"
            className="billing-group-table"
            action={
              <button
                className="secondary"
                disabled={!groups.length}
                onClick={() =>
                  saveCSV(
                    groupedCSV(groups, keys),
                    `starrynight-bailian-${month}-groups.csv`,
                  )
                }
              >
                <Download size={14} />
                导出全部分组 CSV
              </button>
            }
          >
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    {keys.map((k) => (
                      <th key={k}>{labelOf(k)}</th>
                    ))}
                    <th>币种</th>
                    <th>计费明细条数</th>
                    <th>应付金额</th>
                    <th>正向费用占比</th>
                    <th>负向调整 / 退款</th>
                    <th>用量（按单位）</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleGroups.map((g) => (
                    <tr key={JSON.stringify([g.values, g.currency])}>
                      {g.values.map((v, i) => (
                        <td key={keys[i]}>{valueLabel(keys[i], v)}</td>
                      ))}
                      <td>{g.currency}</td>
                      <td className="billing-number">{g.count}</td>
                      <td className="billing-number billing-payable">
                        {g.amounts.PretaxAmount ?? "—"}
                      </td>
                      <td className="billing-number">
                        {percent(
                          g.positive,
                          totals.find((t) => t.currency === g.currency)!
                            .positive,
                        ).toFixed(2)}
                        %
                      </td>
                      <td className="billing-number">{g.refund}</td>
                      <td className="billing-number">
                        <Usage values={g.usage} />
                      </td>
                      <td>
                        <button
                          className="billing-drill"
                          onClick={() => selectGroup(g, keys)}
                        >
                          查看明细
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="pagination">
              <span>
                全部 {groups.length} 组 · 第{" "}
                {Math.min(
                  groupPage + 1,
                  Math.max(1, Math.ceil(groups.length / 25)),
                )}{" "}
                页
              </span>
              <div>
                <button
                  className="secondary"
                  disabled={groupPage === 0}
                  onClick={() => setGroupPage((p) => p - 1)}
                >
                  上一组页
                </button>
                <button
                  className="secondary"
                  disabled={(groupPage + 1) * 25 >= groups.length}
                  onClick={() => setGroupPage((p) => p + 1)}
                >
                  下一组页
                </button>
              </div>
            </div>
          </Panel>
          <Panel
            title="筛选后的全部计费明细"
            className="billing-analysis-details"
            action={
              <button
                className="secondary"
                disabled={!rows.length}
                onClick={downloadDetails}
              >
                <Download size={14} />
                导出筛选明细 CSV
              </button>
            }
          >
            <div className="table-scroll">
              <table className="billing-table">
                <thead>
                  <tr>
                    <th>模型 / 工作空间 / API Key ID</th>
                    <th>商品 / 计费项</th>
                    <th>日期 / 地域</th>
                    <th>输入输出 / 渠道</th>
                    <th>用量 / 单价</th>
                    <th>原始 / 优惠金额</th>
                    <th>应付金额</th>
                    <th>现金 / 未结清</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleRows.map((r, i) => {
                    const m = modelInfo(r.InstanceID);
                    return (
                      <tr key={detailPage * 50 + i}>
                        <td>
                          <strong>
                            {m?.model || r.ProductDetail || "未提供模型"}
                          </strong>
                          <small>
                            工作空间：{dimensionValue(r, "workspace")}
                            <br />
                            API Key ID：{dimensionValue(r, "key")}
                          </small>
                          <details>
                            <summary>查看原始实例 ID</summary>
                            <code>{r.InstanceID || "—"}</code>
                          </details>
                        </td>
                        <td>
                          {dimensionValue(r, "product")}
                          <small>
                            {dimensionValue(r, "item")}
                            <br />
                            {valueLabel(
                              "billType",
                              dimensionValue(r, "billType"),
                            )}
                          </small>
                        </td>
                        <td>
                          {r.BillingDate || month}
                          <small>{r.Region || "未提供"}</small>
                        </td>
                        <td>
                          {dimensionValue(r, "kind")}
                          <small>
                            {valueLabel(
                              "channel",
                              dimensionValue(r, "channel"),
                            )}
                          </small>
                        </td>
                        <td className="billing-number">
                          {r.Usage === undefined
                            ? "—"
                            : `${r.Usage} ${r.UsageUnit || ""}`}
                          <small>
                            {r.ListPrice === undefined
                              ? "—"
                              : `${r.ListPrice} ${r.ListPriceUnit || ""}`}
                          </small>
                        </td>
                        <td className="billing-number">
                          {formatMoney(r.PretaxGrossAmount, r.Currency)}
                          <small>
                            优惠：{formatMoney(r.InvoiceDiscount, r.Currency)}
                            <br />
                            券：
                            {formatMoney(r.DeductedByCashCoupons, r.Currency)}
                            <br />
                            资源包：{r.DeductedByResourcePackage || "—"}
                          </small>
                        </td>
                        <td className="billing-number billing-payable">
                          {formatMoney(r.PretaxAmount, r.Currency)}
                        </td>
                        <td className="billing-number">
                          {formatMoney(r.PaymentAmount, r.Currency)}
                          <small>
                            {formatMoney(r.OutstandingAmount, r.Currency)}
                          </small>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {!rows.length && (
              <div className="state">当前筛选没有计费明细。</div>
            )}
            <div className="pagination">
              <span>
                第{" "}
                {Math.min(
                  detailPage + 1,
                  Math.max(1, Math.ceil(rows.length / 50)),
                )}{" "}
                页 · 本页 {visibleRows.length} 条 · 筛选后共 {rows.length} 条
              </span>
              <div>
                <button
                  className="secondary"
                  disabled={detailPage === 0}
                  onClick={() => setDetailPage((p) => p - 1)}
                >
                  上一明细页
                </button>
                <button
                  className="secondary"
                  disabled={(detailPage + 1) * 50 >= rows.length}
                  onClick={() => setDetailPage((p) => p + 1)}
                >
                  下一明细页
                </button>
              </div>
            </div>
          </Panel>
        </>
      )}
    </div>
  );
}
