// Local fixture rendering, or read-only acceptance against the real admin API.
import { createRequire } from "node:module";
import fs from "node:fs/promises";
import path from "node:path";
const require = createRequire(new URL("../admin-web/package.json", import.meta.url));
const { chromium, expect } = require("@playwright/test");
const base = process.env.ADMIN_TEST_BASE || "http://127.0.0.1:18844";
const fixture = process.env.ADMIN_TEST_BILLING_FIXTURE === "true";
if (fixture && new URL(base).hostname !== "127.0.0.1") throw Error("Billing fixtures require loopback");
const output = process.env.ADMIN_TEST_OUTPUT || ".local/billing-browser";
await fs.mkdir(output, { recursive: true });
const browser = await chromium.launch({ executablePath: process.env.CHROME_EXECUTABLE, headless: true, args: ["--no-proxy-server"] });
const page = await browser.newPage({ viewport: { width: 1512, height: 1050 } });
const errors = [], requests = [];
page.on("pageerror", e => errors.push(e.message));
page.on("request", r => { if (r.url().includes("/admin-api/")) requests.push(new URL(r.url()).pathname); });
let denied = false;
const month = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit" }).format(new Date());
const rows = [
  { ProductName: "大模型服务平台百炼", ProductDetail: "百炼大模型推理", Currency: "CNY", InstanceID: "123;llm-demo;qwen-max;input_token;app;0", BillingItem: "大模型文本消耗量", Usage: "1000", UsageUnit: "Token", ListPrice: "0.000001", ListPriceUnit: "元/Token", PretaxAmount: "0.000001", PretaxGrossAmount: "0.001", InvoiceDiscount: "0", PaymentAmount: "0", OutstandingAmount: "0.000001", Region: "华北2（北京）", Item: "PayAsYouGoBill" },
  { Currency: "CNY", ProductName: "百炼", InstanceID: ";llm-demo;qwen-max;output_token;bmp;0", BillingItem: "退款调整", PretaxAmount: "-0.05", PretaxGrossAmount: "-0.05", PaymentAmount: "0", Item: "Refund" },
];
const analysisRows = [...rows, ...Array.from({ length: 110 }, (_, i) => ({ Currency: "CNY", ProductName: "大模型服务平台百炼", ProductDetail: "百炼大模型推理", InstanceID: `${i % 2 ? "123" : "456"};llm-demo;${i < 70 ? "qwen-max" : "qwen-plus"};${i % 2 ? "output_token" : "input_token"};app;0`, Usage: "100", UsageUnit: "Token", PretaxAmount: "0.01", PretaxGrossAmount: "0.02", InvoiceDiscount: "0.01", PaymentAmount: "0", OutstandingAmount: "0.01", Region: "华北2（北京）", Item: "PayAsYouGoBill" }))];
async function mock() {
  await page.route("**/admin-api/v1/**", async route => {
    const u = new URL(route.request().url()), p = u.pathname;
    let data;
    if (p.endsWith("/session")) data = { user: { id: "fixture-owner", username: "owner", role: "owner" }, csrf: "fixture-token" };
    else if (p.endsWith("/resources")) data = [];
    else if (p.endsWith("/billing/analysis")) {
      const daily = u.searchParams.get("granularity") === "daily";
      data = { status: denied ? "unavailable" : "ready", complete: !denied, month, product: "bailian", view: "analysis", granularity: daily ? "daily" : "monthly", start_date: daily ? month + "-01" : undefined, end_date: daily ? month + "-02" : undefined, fetched_at: new Date().toISOString(), cached: false, rows: denied ? [] : analysisRows.map((r, i) => ({ ...r, ...(daily ? { BillingDate: month + (i % 2 ? "-02" : "-01") } : {}) })), totals: [], next: "", total_count: analysisRows.length, permissions: [] };
      if (denied) data.error = { code: "NotAuthorized", message: "当前阿里云凭据没有账单读取权限。" };
    }
    else if (p.endsWith("/billing")) {
      const view = u.searchParams.get("view") || "overview", product = u.searchParams.get("product") || "bailian";
      data = { status: denied ? "unavailable" : "ready", month, product, view, bucket: view === "bucket" ? "fixture-bucket" : undefined, fetched_at: new Date().toISOString(), cached: false, rows: view === "overview" ? [] : u.searchParams.get("cursor") ? [rows[1]] : rows, totals: view === "overview" ? [{ Currency: "CNY", PretaxAmount: "0.2500001", PaymentAmount: "0.2", OutstandingAmount: "0.0500001", DeductedByCashCoupons: "0" }] : [], next: view === "overview" || u.searchParams.get("cursor") ? "" : "fixture-next", total_count: 3, permissions: ["bss:DescribeBillList", "bssapi:DescribeInstanceBill", "bssapi:DescribeSplitItemBill"] };
      if (denied) { data.rows = []; data.totals = []; data.error = { code: "NotAuthorized", message: "当前阿里云凭据没有账单读取权限，请为所属 RAM 用户或角色附加账单只读策略。" }; }
    } else data = {};
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(data) });
  });
}
async function snap(name, fullPage = true) { await page.screenshot({ path: path.join(output, name + ".png"), fullPage, animations: "disabled" }); }
async function noOverflow() { expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false); }
async function rankingReturn() {
  const ranking = page.locator(".billing-ranking");
  const count = await ranking.locator(".billing-bar").count();
  expect(count).toBeGreaterThan(0);
  await expect(ranking.getByRole("button", { name: "返回上一级", exact: true })).toHaveCount(0);
  await ranking.locator(".billing-bar").first().click();
  await expect(ranking.locator(".billing-bar")).toHaveCount(1);
  // Repeated clicks on the selected model should still need only one return.
  await ranking.locator(".billing-bar").first().click();
  await expect(ranking.getByRole("button", { name: "返回上一级", exact: true })).toBeVisible();
  await ranking.getByRole("button", { name: "返回上一级", exact: true }).click();
  await expect(ranking.locator(".billing-bar")).toHaveCount(count);
  await expect(page.getByLabel("筛选模型", { exact: true })).toHaveValue("");
  await expect(page.getByLabel("筛选币种", { exact: true })).toHaveValue("");
  await expect(ranking.getByRole("button", { name: "返回上一级", exact: true })).toHaveCount(0);
  // The local reset also clears the drill history; no trip to the top is needed.
  await ranking.locator(".billing-bar").first().click();
  await ranking.getByRole("button", { name: "查看全部", exact: true }).click();
  await expect(ranking.locator(".billing-bar")).toHaveCount(count);
  await expect(ranking.getByRole("button", { name: "返回上一级", exact: true })).toHaveCount(0);
}
try {
  if (fixture) await mock();
  await page.goto(base + "/#billing");
  if (!fixture) {
    await expect(page.getByRole("heading", { name: "管理员登录" })).toBeVisible();
    // Use Chrome's network stack: Node's separate APIRequestContext can fail
    // through the host proxy even while the real page reaches production.
    const unauth = await page.evaluate(async month => (await fetch("/admin-api/v1/billing?month=" + month)).status, month);
    expect(unauth).toBe(401);
    await page.getByLabel("账号", { exact: true }).fill(process.env.ADMIN_TEST_USERNAME || "owner");
    await page.getByLabel("密码", { exact: true }).fill((await fs.readFile(process.env.ADMIN_TEST_PASSWORD_FILE, "utf8")).trim());
    await page.getByRole("button", { name: "登录控制台" }).click();
  }
  await expect(page.getByRole("heading", { name: "云服务费用", exact: true })).toBeVisible();
  await expect(page.locator(".billing-summary")).toHaveCount(2);
  await expect(page.getByRole("status").filter({ hasText: "正在读取" })).toHaveCount(0, { timeout: 25000 });
  await expect(page.locator(".billing-analysis-status")).toBeVisible({ timeout: 25000 });
  await rankingReturn();
  if (fixture) {
    await expect(page.locator(".billing-table")).toContainText("0.000001 CNY");
    await expect(page.locator(".billing-table")).toContainText("qwen-max");
    await expect(page.locator(".billing-analysis-status")).toContainText("已完整读取 112 条");
    await page.getByRole("button", { name: "下一明细页", exact: true }).click();
    await expect(page.locator(".billing-analysis-details .pagination")).toContainText("第 2 页");
    await page.getByRole("button", { name: "上一明细页", exact: true }).click();
    // A model drill restores both manual Key and search filters on return.
    const ranking = page.locator(".billing-ranking");
    await page.getByLabel("筛选API Key ID", { exact: true }).selectOption("456");
    await page.getByLabel("搜索账单", { exact: true }).fill("input_token");
    await expect(page.locator(".billing-analysis-status")).toContainText("筛选后 55 条");
    await ranking.getByRole("button", { name: "查看分组 qwen-max CNY", exact: true }).click();
    await expect(page.locator(".billing-analysis-status")).toContainText("筛选后 35 条");
    await ranking.getByRole("button", { name: "返回上一级", exact: true }).click();
    await expect(page.getByLabel("筛选API Key ID", { exact: true })).toHaveValue("456");
    await expect(page.getByLabel("搜索账单", { exact: true })).toHaveValue("input_token");
    await expect(page.getByLabel("筛选模型", { exact: true })).toHaveValue("");
    await expect(page.locator(".billing-analysis-status")).toContainText("筛选后 55 条");
    await ranking.getByRole("button", { name: "查看全部", exact: true }).click();
    await expect(page.getByLabel("搜索账单", { exact: true })).toHaveValue("");
    // Drill from model to Key, then return one level at a time.
    await ranking.getByRole("button", { name: "查看分组 qwen-max CNY", exact: true }).click();
    await page.getByLabel("一级分组", { exact: true }).selectOption("key");
    await ranking.getByRole("button", { name: "查看分组 456 CNY", exact: true }).click();
    await expect(page.getByLabel("筛选API Key ID", { exact: true })).toHaveValue("456");
    await ranking.getByRole("button", { name: "返回上一级", exact: true }).click();
    await expect(page.getByLabel("筛选API Key ID", { exact: true })).toHaveValue("");
    await expect(page.getByLabel("筛选模型", { exact: true })).toHaveValue("qwen-max");
    await ranking.getByRole("button", { name: "返回上一级", exact: true }).click();
    await expect(page.getByLabel("筛选模型", { exact: true })).toHaveValue("");
    await expect(page.locator(".billing-analysis-status")).toContainText("筛选后 112 条");
    await page.getByLabel("一级分组", { exact: true }).selectOption("model");
    // The table uses the same navigation, and editing a filter discards old history.
    const table = page.locator(".billing-group-table");
    await table.getByRole("button", { name: "查看明细", exact: true }).first().click();
    await expect(table.getByRole("button", { name: "返回上一级", exact: true })).toBeVisible();
    await table.getByRole("button", { name: "返回上一级", exact: true }).click();
    await expect(page.locator(".billing-analysis-status")).toContainText("筛选后 112 条");
    await ranking.locator(".billing-bar").first().click();
    await page.getByLabel("搜索账单", { exact: true }).fill("output_token");
    await expect(ranking.getByRole("button", { name: "返回上一级", exact: true })).toHaveCount(0);
    await ranking.getByRole("button", { name: "查看全部", exact: true }).click();
    await page.getByLabel("二级分组", { exact: true }).selectOption("key");
    await expect(page.locator(".billing-group-table")).toContainText("456");
    await page.getByLabel("筛选模型", { exact: true }).selectOption("qwen-max");
    await expect(page.locator(".billing-analysis-status")).toContainText("筛选后 72 条");
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: "导出筛选明细 CSV" }).click();
    await (await download).saveAs(path.join(output, "fixture-bill.csv"));
    expect((await fs.readFile(path.join(output, "fixture-bill.csv"), "utf8")).split("\r\n")).toHaveLength(73);
    const grouped = page.waitForEvent("download");
    await page.getByRole("button", { name: "导出全部分组 CSV" }).click();
    await (await grouped).saveAs(path.join(output, "fixture-groups.csv"));
    await page.getByRole("button", { name: "清除全部筛选", exact: true }).click();
    await page.getByLabel("统计颗粒度", { exact: true }).selectOption("daily");
    await expect(page.getByRole("heading", { name: "按日费用趋势", exact: true })).toBeVisible();
    await page.getByRole("button", { name: `筛选日期 ${month}-01 CNY`, exact: true }).click();
    await expect(page.locator(".billing-analysis-status")).toContainText("筛选后 56 条");
    await page.locator(".billing-trend").getByRole("button", { name: "返回上一级", exact: true }).click();
    await expect(page.locator(".billing-analysis-status")).toContainText("筛选后 112 条");
  }
  await snap("billing-desktop"); await noOverflow();
  await page.locator(".billing-statistics").scrollIntoViewIfNeeded();
  await snap("analysis-panels-desktop", false);
  await page.setViewportSize({ width: 390, height: 844 });
  if (fixture) await page.getByLabel("二级分组", { exact: true }).selectOption("");
  await rankingReturn();
  await page.locator(".billing-ranking .billing-bar").first().click();
  await noOverflow();
  await page.locator(".billing-ranking").scrollIntoViewIfNeeded();
  await snap("ranking-navigation-mobile", false);
  await page.locator(".billing-ranking").getByRole("button", { name: "返回上一级", exact: true }).click();
  await noOverflow(); await snap("billing-data-mobile");
  await page.locator(".billing-chart-grid").scrollIntoViewIfNeeded();
  await snap("analysis-charts-mobile", false);
  await page.setViewportSize({ width: 1512, height: 1050 });
  await page.getByRole("tab", { name: "OSS", exact: true }).click();
  await page.getByLabel("费用范围").selectOption("bucket");
  await expect(page.getByRole("heading", { name: "项目 Bucket 分账明细" })).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: "正在读取" })).toHaveCount(0, { timeout: 25000 });
  await snap("bucket-desktop");
  if (fixture) {
    denied = true;
    await page.getByRole("tab", { name: "百炼", exact: true }).click();
    await page.getByRole("button", { name: "刷新", exact: true }).click();
    await expect(page.locator(".billing-problem")).toHaveCount(3);
    await expect(page.locator(".billing-amounts")).toHaveCount(0);
    await snap("permission-desktop");
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await noOverflow(); await snap("billing-mobile");
  expect(errors).toEqual([]);
  expect(requests.some(p => /restart|mutate|\/create\//.test(p))).toBe(false);
  await fs.writeFile(path.join(output, "result.json"), JSON.stringify({ base, fixture, browser_errors: errors, checked: ["authentication", "desktop", "mobile", "bucket_scope", "ranking_return", "ranking_reset", "repeated_drill", ...(fixture ? ["small_amounts", "refund", "pagination", "csv_all_filtered_rows", "two_dimensions", "model_filter", "daily_trend", "drill_down", "manual_filter_restore", "two_level_return", "table_return", "manual_edit_resets_history", "permission_state"] : [])], requests }, null, 2));
  console.log(JSON.stringify({ verified: true, fixture, output }));
} finally { await browser.close(); }
