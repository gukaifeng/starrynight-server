// Read-only browser acceptance. No provider calls, production fixtures or writes.
import { createRequire } from "node:module";
import fs from "node:fs/promises";
import path from "node:path";
const require = createRequire(
  new URL("../admin-web/package.json", import.meta.url),
);
const { chromium, expect } = require("@playwright/test");
const base = process.env.ADMIN_TEST_BASE ?? "http://127.0.0.1:18744";
const output =
  process.env.ADMIN_TEST_OUTPUT ?? ".local/admin-dimensions-browser";
await fs.mkdir(output, { recursive: true });
const browser = await chromium.launch({
  executablePath: process.env.CHROME_EXECUTABLE,
  headless: true,
  args: process.env.ADMIN_TEST_DIRECT === "true" ? ["--no-proxy-server"] : [],
});
const context = await browser.newContext({
  viewport: { width: 1512, height: 1050 },
});
const page = await context.newPage();
const errors = [],
  apiErrors = [],
  requests = [];
page.on("pageerror", (e) => errors.push(e.message));
page.on("request", (r) => {
  if (r.url().includes("/admin-api/")) requests.push(new URL(r.url()).pathname);
});
page.on("response", (r) => {
  if (
    r.url().includes("/admin-api/") &&
    !r.url().includes("/record-images/") &&
    r.status() >= 500
  )
    apiErrors.push({ path: new URL(r.url()).pathname, status: r.status() });
});
async function call(endpoint) {
  return page.evaluate(async (endpoint) => {
    const response = await fetch("/admin-api/v1" + endpoint);
    return { status: response.status, data: await response.json() };
  }, endpoint);
}
async function nav(label) {
  const button = page
    .locator(".sidebar")
    .getByRole("button", { name: label, exact: true });
  if (
    (await page.getByRole("button", { name: "打开导航" }).isVisible()) &&
    (await page
      .locator(".sidebar")
      .evaluate((el) => el.getBoundingClientRect().right <= 1))
  )
    await page.getByRole("button", { name: "打开导航" }).click();
  await button.click();
}
async function noOverflow() {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
  ).toBe(false);
}
try {
  await page.goto(base);
  expect((await call("/directory/users")).status).toBe(401);
  expect((await call("/directory/characters")).status).toBe(401);
  await page
    .getByLabel("账号", { exact: true })
    .fill(process.env.ADMIN_TEST_USERNAME ?? "owner");
  await page
    .getByLabel("密码", { exact: true })
    .fill(
      (await fs.readFile(process.env.ADMIN_TEST_PASSWORD_FILE, "utf8")).trim(),
    );
  await page.getByRole("button", { name: "进入控制室" }).click();
  await expect(
    page.getByRole("heading", { name: "用户", exact: true }),
  ).toBeVisible();
  await page.locator(".entity-directory-table tbody tr").first().waitFor();
  expect(requests.filter((p) => p.endsWith("/overview"))).toEqual([]);
  if (process.env.ADMIN_TEST_FIXTURE === "true") {
    await page.getByLabel("每页数量").selectOption("10");
    await expect(page.locator(".entity-directory-table tbody tr")).toHaveCount(
      10,
    );
    await page.getByRole("button", { name: "下一页", exact: true }).click();
    await expect(page.locator(".entity-pagination")).toContainText("第 2 页");
    await page.getByRole("button", { name: "上一页", exact: true }).click();
    await expect(page.locator(".entity-pagination")).toContainText("第 1 页");
    await page.getByLabel("搜索用户").fill("演示用户 1");
    await expect(page.locator(".entity-directory-table tbody tr")).toHaveCount(
      10,
    );
    // 10-row pages mean 11 matches span two pages; search a unique whole UUID.
  }
  await page.screenshot({
    path: path.join(output, "users-desktop.png"),
    fullPage: true,
    animations: "disabled",
  });
  const userPage = await call("/directory/users?limit=1");
  expect(userPage.status).toBe(200);
  const userId =
    process.env.ADMIN_TEST_FIXTURE === "true"
      ? (await fs.readFile(".local/browser-fixture-user", "utf8")).trim()
      : userPage.data.items[0].id;
  await page.getByLabel("搜索用户").fill(userId);
  await expect(page.locator(".entity-directory-table tbody tr")).toHaveCount(1);
  await page.locator(".entity-directory-table tbody tr").click();
  await expect(page.locator(".entity-hero")).toBeVisible();
  await expect(page.locator(".worker-summary")).toContainText("上下文消息");
  await expect(page.locator(".entity-info")).not.toHaveCount(0);
  await page.screenshot({
    path: path.join(output, "user-detail-desktop.png"),
    fullPage: true,
    animations: "disabled",
  });
  await page.getByRole("tab", { name: "角色与羁绊", exact: true }).click();
  await page.locator(".relationships-panel tbody tr").first().waitFor();
  await page.screenshot({
    path: path.join(output, "user-relationships-desktop.png"),
    fullPage: true,
    animations: "disabled",
  });
  await page
    .getByRole("button", { name: "关系与记录", exact: true })
    .first()
    .click();
  await expect(page.locator(".relationship-path")).toBeVisible();
  await expect(page.locator(".scoped-data")).toBeVisible();
  await page.getByLabel("账户数据分类").selectOption("conversation_goals");
  await expect(
    page.getByRole("heading", { name: "关系与目标", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "AI 上下文与运行记录", exact: true })
    .click();
  await expect(page.getByLabel("AI 数据分类")).toBeVisible();
  await page.getByLabel("AI 数据分类").selectOption("memories");
  await expect(
    page.getByRole("heading", { name: "AI 记忆", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: path.join(output, "relationship-records-desktop.png"),
    fullPage: true,
    animations: "disabled",
  });
  await page.locator(".relationship-path").getByRole("button").last().click();
  await expect(page.locator(".entity-hero")).toBeVisible();
  await page
    .getByRole("tab", { name: "订阅者与对话用户", exact: true })
    .click();
  await page.getByLabel("关系范围").selectOption("subscribers");
  await page.locator(".relationships-panel tbody tr").first().waitFor();
  await page.screenshot({
    path: path.join(output, "character-subscribers-desktop.png"),
    fullPage: true,
    animations: "disabled",
  });
  await page
    .getByRole("button", { name: "用户页", exact: true })
    .first()
    .click();
  await expect(
    page.getByRole("tab", { name: "角色与羁绊", exact: true }),
  ).toBeVisible();
  await nav("角色维度");
  await page.locator(".entity-directory-table tbody tr").first().waitFor();
  await page.getByLabel("每页数量").selectOption("10");
  await expect(page.locator(".entity-directory-table tbody tr")).toHaveCount(
    10,
  );
  await page.getByRole("button", { name: "下一页", exact: true }).click();
  await expect(page.locator(".entity-pagination")).toContainText("第 2 页");
  await page.getByRole("button", { name: "上一页", exact: true }).click();
  await expect(page.locator(".entity-pagination")).toContainText("第 1 页");
  await page.getByLabel("搜索角色").fill("anime-kipfel");
  await expect(page.locator(".entity-directory-table tbody tr")).toHaveCount(2);
  await page
    .locator('.entity-directory-table tbody tr[data-entity-id="anime-kipfel"]')
    .click();
  await page.getByRole("tab", { name: "AI 运行数据", exact: true }).click();
  await page.locator(".scoped-data tbody tr").first().waitFor();
  await page.locator(".scoped-data tbody tr").first().click();
  await expect(
    page.getByRole("tab", { name: "编辑", exact: true }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "编辑", exact: true }).click();
  await expect(
    page.getByRole("textbox", { name: "职业", exact: true }),
  ).toBeVisible();
  await page
    .locator(".detail-panel")
    .getByRole("button", { name: "关闭详情" })
    .click();
  await page
    .getByRole("tab", { name: "订阅者与对话用户", exact: true })
    .click();
  await page.getByLabel("关系范围").selectOption("ai");
  await expect(
    page.locator(".relationships-panel .entity-state"),
  ).not.toBeVisible();
  await nav("后台数据维度");
  await expect(
    page.getByRole("heading", { name: "后台数据", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: path.join(output, "backend-desktop.png"),
    fullPage: true,
    animations: "disabled",
  });
  await page
    .locator(".backend-groups")
    .getByRole("button", { name: /聊天记录/ })
    .click();
  await expect(
    page.getByRole("heading", { name: "聊天记录", exact: true }),
  ).toBeVisible();
  await nav("语音耗时");
  await expect(
    page.getByRole("heading", { name: "语音耗时", exact: true }),
  ).toBeVisible();
  await nav("后台数据维度");
  await noOverflow();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: path.join(output, "backend-mobile.png"),
    fullPage: true,
    animations: "disabled",
  });
  await noOverflow();
  await nav("用户维度");
  await page.locator(".entity-directory-table tbody tr").first().click();
  await expect(page.locator(".entity-hero")).toBeVisible();
  await page.screenshot({
    path: path.join(output, "user-mobile.png"),
    fullPage: true,
    animations: "disabled",
  });
  await noOverflow();
  await nav("角色维度");
  await page.locator(".entity-directory-table tbody tr").first().click();
  await expect(page.locator(".entity-hero")).toBeVisible();
  await page.screenshot({
    path: path.join(output, "character-mobile.png"),
    fullPage: true,
    animations: "disabled",
  });
  await noOverflow();
  await page.reload();
  await expect(page.locator(".entity-hero")).toBeVisible();
  expect(errors).toEqual([]);
  expect(apiErrors).toEqual([]);
  const report = {
    passed: true,
    base,
    paid_calls: 0,
    page_errors: errors,
    api_errors: apiErrors,
    dimensions: ["users", "characters", "backend"],
    viewports: ["1512×1050", "390×844"],
    checks: [
      "authentication",
      "no-eager-counts",
      "pagination",
      "search",
      "scoped-records",
      "user-character-links",
      "AI-profile-editor",
      "legacy-worker-scopes",
      "voice-timings",
      "hash-reload",
      "overflow",
    ],
  };
  await fs.writeFile(
    path.join(output, "result.json"),
    JSON.stringify(report, null, 2),
  );
  console.log(JSON.stringify(report));
} catch (error) {
  await page.screenshot({
    path: path.join(output, "failure.png"),
    fullPage: true,
    animations: "disabled",
  });
  throw error;
} finally {
  await browser.close();
}
