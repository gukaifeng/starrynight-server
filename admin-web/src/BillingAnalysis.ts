// Official amounts stay decimal strings. JS Number is only used for chart
// geometry, never for sums, ordering, CSV totals, or displayed money.
export type BillRow = Record<string, string>;
type Decimal = { n: bigint; scale: number };
function decimal(value?: string): Decimal | null {
  const m = value
    ?.trim()
    .match(/^([+-]?)(\d+)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/);
  if (!m) return null;
  const exponent = Number(m[4] || 0);
  if (!Number.isInteger(exponent) || Math.abs(exponent) > 1000) return null;
  const fraction = m[3] || "",
    scale = fraction.length - exponent;
  let n = BigInt(m[2] + fraction) * (m[1] === "-" ? -1n : 1n);
  if (scale < 0) n *= 10n ** BigInt(-scale);
  return { n, scale: Math.max(0, scale) };
}
function decimalText({ n, scale }: Decimal) {
  if (!n) return "0";
  const sign = n < 0 ? "-" : "",
    text = (n < 0 ? -n : n).toString().padStart(scale + 1, "0");
  return (
    sign +
    (scale
      ? (text.slice(0, -scale) + "." + text.slice(-scale)).replace(/\.?0+$/, "")
      : text)
  );
}
export function addDecimal(a: string, b: string): string {
  const x = decimal(a),
    y = decimal(b);
  if (!x || !y) throw new Error("Invalid decimal");
  const scale = Math.max(x.scale, y.scale);
  return decimalText({
    n:
      x.n * 10n ** BigInt(scale - x.scale) +
      y.n * 10n ** BigInt(scale - y.scale),
    scale,
  });
}
export function compareDecimal(a: string, b: string) {
  const x = decimal(a) || { n: 0n, scale: 0 },
    y = decimal(b) || { n: 0n, scale: 0 };
  const scale = Math.max(x.scale, y.scale),
    difference =
      x.n * 10n ** BigInt(scale - x.scale) -
      y.n * 10n ** BigInt(scale - y.scale);
  return difference < 0n ? -1 : difference > 0n ? 1 : 0;
}
export function percent(part: string, total: string) {
  const p = decimal(part),
    t = decimal(total);
  if (!p || !t || p.n <= 0 || t.n <= 0) return 0;
  const scale = Math.max(p.scale, t.scale);
  return (
    Number(
      (p.n * 10n ** BigInt(scale - p.scale) * 10000n) /
        (t.n * 10n ** BigInt(scale - t.scale)),
    ) / 100
  );
}

export function modelInfo(id = "") {
  const parts = id.split(";").map((v) => v.trim());
  if (parts.length === 6)
    return {
      key: parts[0],
      workspace: parts[1],
      model: parts[2],
      kind: parts[3],
      channel: parts[4],
      quota: parts[5],
    };
  // Observed BSS inference rows (speech/image/translation) omit the channel:
  // key;workspace;model;meter;quota. Require a recognizable space and boolean
  // final flag, preserve the original ID, and never invent a missing channel.
  if (
    parts.length === 5 &&
    /^(llm-|ws-)[A-Za-z0-9-]+$/.test(parts[1]) &&
    parts[2] &&
    parts[3] &&
    /^[01]$/.test(parts[4])
  ) {
    return {
      key: parts[0],
      workspace: parts[1],
      model: parts[2],
      kind: parts[3],
      channel: "",
      quota: parts[4],
    };
  }
  return null;
}
export const dimensions = [
  ["model", "模型"],
  ["key", "API Key ID"],
  ["workspace", "工作空间"],
  ["kind", "输入 / 输出类型"],
  ["channel", "调用渠道"],
  ["region", "地域"],
  ["product", "商品 / 服务"],
  ["item", "计费项"],
  ["billType", "账单类型"],
  ["subscription", "付费方式"],
  ["tag", "实例标签"],
  ["costUnit", "财务单元"],
  ["resourceGroup", "资源组"],
  ["quota", "免费额度用完即停标识"],
  ["date", "账单日期"],
] as const;
export type Dimension = (typeof dimensions)[number][0];
export type Filters = Partial<Record<Dimension | "currency", string>>;
const unknown = "未提供";
export function dimensionValue(row: BillRow, key: Dimension) {
  const m = modelInfo(row.InstanceID);
  const training = row.InstanceID?.split("!").map((v) => v.trim());
  switch (key) {
    case "model":
      return m?.model || unknown;
    case "key":
      return m ? m.key || "未提供 API Key ID" : unknown;
    case "workspace":
      return (
        m?.workspace || (training?.length === 3 ? training[0] : "") || unknown
      );
    case "kind":
      return m?.kind || unknown;
    case "channel":
      return m?.channel || unknown;
    case "quota":
      return m?.quota || unknown;
    case "region":
      return row.Region || unknown;
    case "product":
      return (
        row.ProductDetail || row.ProductName || row.CommodityCode || unknown
      );
    case "item":
      return row.BillingItem || row.BillingItemCode || unknown;
    case "billType":
      return row.Item || unknown;
    case "subscription":
      return row.SubscriptionType || unknown;
    case "tag":
      return row.Tag || "无标签";
    case "costUnit":
      return row.CostUnit || "未分配";
    case "resourceGroup":
      return row.ResourceGroup || unknown;
    case "date":
      return row.BillingDate || "月汇总（无逐日日期）";
  }
}
export function valueLabel(dimension: Dimension, value: string) {
  const labels: Partial<Record<Dimension, Record<string, string>>> = {
    channel: {
      app: "应用程序 · app",
      bmp: "控制台体验 · bmp",
      "assistant-api": "Assistant API",
    },
    billType: {
      Refund: "退款",
      Adjustment: "调账",
      SubscriptionOrder: "预付订单",
      PayAsYouGoBill: "后付账单",
    },
    subscription: { Subscription: "预付费", PayAsYouGo: "后付费" },
    quota: {
      "0": "0 · 未启用免费额度用完即停",
      "1": "1 · 启用免费额度用完即停",
    },
  };
  return labels[dimension]?.[value] || value;
}
export function filterRows(rows: BillRow[], filters: Filters, search = "") {
  const needle = search.trim().toLocaleLowerCase();
  return rows.filter(
    (row) =>
      Object.entries(filters).every(
        ([k, v]) =>
          !v ||
          (k === "currency"
            ? row.Currency
            : dimensionValue(row, k as Dimension)) === v,
      ) &&
      (!needle ||
        Object.values(row).some((v) => v.toLocaleLowerCase().includes(needle))),
  );
}

export const amountFields = [
  "PretaxAmount",
  "PretaxGrossAmount",
  "InvoiceDiscount",
  "DeductedByCashCoupons",
  "PaymentAmount",
  "OutstandingAmount",
] as const;
export type Aggregate = {
  values: string[];
  currency: string;
  count: number;
  amounts: BillRow;
  positive: string;
  refund: string;
  usage: BillRow;
  missingAmount: number;
};
export function aggregate(
  rows: BillRow[],
  keys: Dimension[] = [],
): Aggregate[] {
  const groups = new Map<string, Aggregate>();
  for (const row of rows) {
    const values = keys.map((k) => dimensionValue(row, k)),
      currency = row.Currency || "未标明";
    const id = JSON.stringify([values, currency]);
    let group = groups.get(id);
    if (!group) {
      group = {
        values,
        currency,
        count: 0,
        amounts: {},
        positive: "0",
        refund: "0",
        usage: {},
        missingAmount: 0,
      };
      groups.set(id, group);
    }
    group.count++;
    for (const field of amountFields)
      if (decimal(row[field]))
        group.amounts[field] = addDecimal(
          group.amounts[field] || "0",
          row[field],
        );
    if (!decimal(row.PretaxAmount)) group.missingAmount++;
    else if (compareDecimal(row.PretaxAmount, "0") >= 0)
      group.positive = addDecimal(group.positive, row.PretaxAmount);
    else group.refund = addDecimal(group.refund, row.PretaxAmount);
    // Missing units are not safely comparable and are deliberately not summed.
    if (row.UsageUnit && decimal(row.Usage))
      group.usage[row.UsageUnit] = addDecimal(
        group.usage[row.UsageUnit] || "0",
        row.Usage,
      );
  }
  return [...groups.values()];
}
export function csvTable(headers: string[], rows: string[][]) {
  const cell = (v: string) =>
    `"${(/^[=+\-@\t\r]/.test(v) ? "'" + v : v).replaceAll('"', '""')}"`;
  return (
    "\uFEFF" +
    [headers, ...rows].map((row) => row.map(cell).join(",")).join("\r\n")
  );
}
export function groupedCSV(groups: Aggregate[], keys: Dimension[]) {
  return csvTable(
    [
      ...keys.map((k) => dimensions.find((d) => d[0] === k)![1]),
      "币种",
      "计费明细条数",
      "应付金额",
      "原始金额",
      "优惠金额",
      "代金券抵扣",
      "现金支付",
      "未结清",
      "正向费用",
      "负向调整 / 退款",
      "用量（按单位）",
    ],
    groups.map((g) => [
      ...g.values,
      g.currency,
      String(g.count),
      ...amountFields.map((f) => g.amounts[f] ?? ""),
      g.positive,
      g.refund,
      Object.entries(g.usage)
        .map(([u, v]) => `${v} ${u}`)
        .join("; "),
    ]),
  );
}
