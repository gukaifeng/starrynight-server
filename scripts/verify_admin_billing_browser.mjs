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
async function mock() {
  await page.route("**/admin-api/v1/**", async route => {
    const u = new URL(route.request().url()), p = u.pathname;
    let data;
    if (p.endsWith("/session")) data = { user: { id: "fixture-owner", username: "owner", role: "owner" }, csrf: "fixture-token" };
    else if (p.endsWith("/resources")) data = [];
    else if (p.endsWith("/billing")) {
      const view = u.searchParams.get("view") || "overview", product = u.searchParams.get("product") || "bailian";
      data = { status: denied ? "unavailable" : "ready", month, product, view, bucket: view === "bucket" ? "fixture-bucket" : undefined, fetched_at: new Date().toISOString(), cached: false, rows: view === "overview" ? [] : u.searchParams.get("cursor") ? [rows[1]] : rows, totals: view === "overview" ? [{ Currency: "CNY", PretaxAmount: "0.2500001", PaymentAmount: "0.2", OutstandingAmount: "0.0500001", DeductedByCashCoupons: "0" }] : [], next: view === "overview" || u.searchParams.get("cursor") ? "" : "fixture-next", total_count: 3, permissions: ["bss:DescribeBillList", "bssapi:DescribeInstanceBill", "bssapi:DescribeSplitItemBill"] };
      if (denied) { data.rows = []; data.totals = []; data.error = { code: "NotAuthorized", message: "当前阿里云凭据没有账单读取权限，请为所属 RAM 用户或角色附加账单只读策略。" }; }
    } else data = {};
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(data) });
  });
}
async function snap(name) { await page.screenshot({ path: path.join(output, name + ".png"), fullPage: true, animations: "disabled" }); }
async function noOverflow() { expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false); }
try {
  if (fixture) await mock();
  await page.goto(base + "/#billing");
  if (!fixture) {
    await expect(page.getByRole("heading", { name: "管理员登录" })).toBeVisible();
    const unauth = await page.request.get(base + "/admin-api/v1/billing?month=" + month);
    expect(unauth.status()).toBe(401);
    await page.getByLabel("账号", { exact: true }).fill(process.env.ADMIN_TEST_USERNAME || "owner");
    await page.getByLabel("密码", { exact: true }).fill((await fs.readFile(process.env.ADMIN_TEST_PASSWORD_FILE, "utf8")).trim());
    await page.getByRole("button", { name: "登录控制台" }).click();
  }
  await expect(page.getByRole("heading", { name: "云服务费用", exact: true })).toBeVisible();
  await expect(page.locator(".billing-summary")).toHaveCount(2);
  await expect(page.getByRole("status").filter({ hasText: "正在读取" })).toHaveCount(0, { timeout: 25000 });
  if (fixture) {
    await expect(page.locator(".billing-table")).toContainText("0.000001 CNY");
    await expect(page.locator(".billing-table")).toContainText("qwen-max");
    await page.getByRole("button", { name: "下一页", exact: true }).click();
    await expect(page.locator(".pagination")).toContainText("第 2 页");
    await page.getByRole("button", { name: "上一页", exact: true }).click();
    await expect(page.locator(".pagination")).toContainText("第 1 页");
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: "导出本页 CSV" }).click();
    await (await download).saveAs(path.join(output, "fixture-bill.csv"));
  }
  await snap("billing-desktop"); await noOverflow();
  await page.setViewportSize({ width: 390, height: 844 });
  await noOverflow(); await snap("billing-data-mobile");
  await page.setViewportSize({ width: 1512, height: 1050 });
  await page.getByRole("tab", { name: "OSS", exact: true }).click();
  await page.getByLabel("费用范围").selectOption("bucket");
  await expect(page.getByRole("heading", { name: "项目 Bucket 分账明细" })).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: "正在读取" })).toHaveCount(0, { timeout: 25000 });
  await snap("bucket-desktop");
  if (fixture) {
    denied = true;
    await page.getByRole("button", { name: "刷新", exact: true }).click();
    await expect(page.locator(".billing-problem")).toHaveCount(3);
    await expect(page.locator(".billing-amounts")).toHaveCount(0);
    await snap("permission-desktop");
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await noOverflow(); await snap("billing-mobile");
  expect(errors).toEqual([]);
  expect(requests.some(p => /restart|mutate|\/create\//.test(p))).toBe(false);
  await fs.writeFile(path.join(output, "result.json"), JSON.stringify({ base, fixture, browser_errors: errors, checked: ["authentication", "desktop", "mobile", "bucket_scope", ...(fixture ? ["small_amounts", "refund", "pagination", "csv", "permission_state"] : [])], requests }, null, 2));
  console.log(JSON.stringify({ verified: true, fixture, output }));
} finally { await browser.close(); }
