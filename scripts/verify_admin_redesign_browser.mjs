// Authenticated browser acceptance. Production is read-only; synthetic writes
// require an explicit local-fixture flag and a loopback target.
import { createRequire } from "node:module";
import fs from "node:fs/promises";
import path from "node:path";
const require = createRequire(
  new URL("../admin-web/package.json", import.meta.url),
);
const { chromium, expect } = require("@playwright/test");
const base = process.env.ADMIN_TEST_BASE || "http://127.0.0.1:18744";
const output = process.env.ADMIN_TEST_OUTPUT || ".local/admin-redesign-browser";
const writes = process.env.ADMIN_TEST_MUTATIONS === "true";
if (writes && !["127.0.0.1", "localhost"].includes(new URL(base).hostname))
  throw Error("Fixture writes require a loopback server");
await fs.mkdir(output, { recursive: true });
const browser = await chromium.launch({
  executablePath: process.env.CHROME_EXECUTABLE,
  headless: true,
  args: process.env.ADMIN_TEST_DIRECT === "true" ? ["--no-proxy-server"] : [],
});
const page = await browser.newPage({ viewport: { width: 1512, height: 1050 } });
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
const heading = (name) => page.getByRole("heading", { name, exact: true });
const snap = async (name) => {
  await page.screenshot({
    path: path.join(output, name + ".png"),
    fullPage: true,
    animations: "disabled",
  });
};
const noOverflow = async () =>
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
  ).toBe(false);
async function nav(name) {
  if (
    (await page.getByRole("button", { name: "打开导航" }).isVisible()) &&
    (await page
      .locator(".sidebar")
      .evaluate((el) => !el.classList.contains("is-open")))
  )
    await page.getByRole("button", { name: "打开导航" }).click();
  await page
    .locator(".sidebar")
    .getByRole("button", { name, exact: true })
    .click();
}
async function call(p) {
  return page.evaluate(async (p) => {
    const r = await fetch("/admin-api/v1" + p);
    return { status: r.status, data: await r.json() };
  }, p);
}
async function route(hash) {
  await page.evaluate((hash) => {
    location.hash = encodeURIComponent(hash);
  }, hash);
}
try {
  await page.goto(base);
  await expect(heading("管理员登录")).toBeVisible();
  expect((await call("/directory/users")).status).toBe(401);
  expect((await call("/directory/characters")).status).toBe(401);
  await snap("login-desktop");
  await page
    .getByLabel("账号", { exact: true })
    .fill(process.env.ADMIN_TEST_USERNAME || "owner");
  await page
    .getByLabel("密码", { exact: true })
    .fill(
      (await fs.readFile(process.env.ADMIN_TEST_PASSWORD_FILE, "utf8")).trim(),
    );
  await page.getByRole("button", { name: "登录控制台" }).click();
  await expect(heading("用户")).toBeVisible();
  await page.locator(".entity-directory-table tbody tr").first().waitFor();
  expect(requests.filter((p) => p.endsWith("/overview"))).toEqual([]);
  await snap("users-desktop");
  if (process.env.ADMIN_TEST_FIXTURE === "true") {
    await page.getByLabel("每页数量").selectOption("10");
    await expect(page.locator(".entity-directory-table tbody tr")).toHaveCount(
      10,
    );
    await page.getByRole("button", { name: "下一页", exact: true }).click();
    await expect(page.locator(".pagination")).toContainText("第 2 页");
    await page.getByRole("button", { name: "上一页", exact: true }).click();
    await expect(page.locator(".pagination")).toContainText("第 1 页");
  }
  const firstUser = (await call("/directory/users?limit=1")).data.items[0];
  const userId =
    process.env.ADMIN_TEST_FIXTURE === "true"
      ? (await fs.readFile(".local/browser-fixture-user", "utf8")).trim()
      : firstUser.id;
  await page.getByLabel("搜索用户").fill(userId);
  await expect(page.locator(".entity-directory-table tbody tr")).toHaveCount(1);
  await page.locator(".entity-directory-table tbody tr").click();
  await expect(page.locator(".entity-hero")).toBeVisible();
  await expect(page.locator(".worker-summary")).toContainText("上下文消息");
  await expect(heading("账户资料")).toBeVisible();
  await snap("user-detail-desktop");
  await noOverflow();
  await page.getByRole("button", { name: "管理资料", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("tab", { name: "编辑", exact: true })
    .click();
  await expect(
    page.getByRole("dialog").getByLabel("昵称", { exact: true }),
  ).toBeVisible();
  await snap("user-editor-desktop");
  await page.getByLabel("关闭详情", { exact: true }).click();
  await page.getByRole("tab", { name: "角色与羁绊", exact: true }).click();
  await page.locator(".relationships-panel tbody tr").first().waitFor();
  await snap("user-relations-desktop");
  await page
    .getByRole("button", { name: "关系与记录", exact: true })
    .first()
    .click();
  await expect(page.locator(".relationship-path")).toBeVisible();
  await expect(heading("关系与目标").first()).toBeVisible();
  await page.getByLabel("账户数据分类").selectOption("conversation_goals");
  await expect(heading("关系与目标")).toHaveCount(2);
  await page
    .getByRole("tab", { name: "AI 上下文与运行记录", exact: true })
    .click();
  await page.getByLabel("AI 数据分类").selectOption("memories");
  await expect(heading("AI 记忆")).toBeVisible();
  await snap("relationship-records-desktop");
  await page
    .locator(".relationship-path>div")
    .getByRole("button")
    .last()
    .click();
  await expect(page.locator(".entity-hero")).toBeVisible();
  await snap("character-detail-desktop");
  await page
    .getByRole("tab", { name: "订阅者与对话用户", exact: true })
    .click();
  await page.getByLabel("关系范围").selectOption("subscribers");
  await page.locator(".relationships-panel tbody tr").first().waitFor();
  await page
    .getByRole("button", { name: "用户页", exact: true })
    .first()
    .click();
  await expect(page.getByRole("tab", { name: "角色与羁绊" })).toBeVisible();
  await nav("角色维度");
  await page.getByLabel("每页数量").selectOption("10");
  await expect(page.locator(".entity-directory-table tbody tr")).toHaveCount(
    10,
  );
  await page.getByRole("button", { name: "下一页", exact: true }).click();
  await expect(page.locator(".pagination")).toContainText("第 2 页");
  await page.getByRole("button", { name: "上一页", exact: true }).click();
  await snap("characters-desktop");
  await page.getByLabel("搜索角色").fill("anime-kipfel");
  await expect(page.locator(".entity-directory-table tbody tr")).toHaveCount(2);
  await page.locator('tr[data-entity-id="anime-kipfel"]').click();
  await expect(heading("头像与封面")).toBeVisible();
  await page.getByRole("tab", { name: "AI 运行数据", exact: true }).click();
  await page.locator(".scoped-data tbody tr").first().waitFor();
  await page.locator(".scoped-data tbody tr").first().click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("tab", { name: "编辑", exact: true }).click();
  await expect(dialog.getByLabel("职业", { exact: true })).toBeVisible();
  await expect(
    dialog.getByRole("textbox", { name: "年龄", exact: true }),
  ).toHaveCount(0);
  await snap("ai-profile-editor-desktop");
  await page.getByLabel("关闭详情", { exact: true }).click();
  await page
    .getByRole("tab", { name: "订阅者与对话用户", exact: true })
    .click();
  await page.getByLabel("关系范围").selectOption("ai");
  await expect(page.locator(".relationships-panel .state")).toHaveCount(0);
  await nav("后台数据维度");
  await expect(heading("后台数据")).toBeVisible();
  await expect(page.locator(".catalog-item")).toHaveCount(
    (await call("/resources")).data.length +
      (await call("/ai/console/resources")).data.length,
  );
  await snap("backend-desktop");
  await page.getByLabel("搜索后台数据").fill("聊天记录");
  await expect(page.locator(".catalog-item")).toHaveCount(1);
  await page.locator(".catalog-item").click();
  await expect(heading("聊天记录")).toBeVisible();
  await nav("总览");
  await expect(heading("服务与数据总览")).toBeVisible();
  await page.locator(".service-grid").waitFor();
  await snap("overview-desktop");
  await nav("语音耗时");
  await expect(heading("语音耗时")).toBeVisible();
  await snap("voice-desktop");
  for (const [id, name] of [
    ["library", "资源与模型"],
    ["audio", "声音文件"],
    ["cache", "会话与缓存"],
    ["backups", "备份与恢复"],
    ["config", "运行配置"],
    ["releases", "版本与证书"],
    ["files", "服务器文件"],
    ["jobs", "维护任务"],
  ]) {
    await route("manage:" + id);
    await expect(heading(name)).toBeVisible();
    await expect(page.locator(".management-workspace .error-note")).toHaveCount(
      0,
    );
    if (["library", "config", "audio"].includes(id)) {
      await page.waitForTimeout(500);
      await snap("management-" + id + "-desktop");
      await noOverflow();
    }
  }
  await route("manage:config");
  await expect(
    page.getByLabel("百炼 API Key", { exact: true }),
  ).toHaveAttribute("type", "password");
  expect(
    await page.getByLabel("百炼 API Key", { exact: true }).inputValue(),
  ).toBe("");
  if (writes) {
    await route("users");
    await page.getByRole("button", { name: "新建", exact: true }).click();
    const create = page.getByRole("dialog");
    const username = "redesign_" + Date.now();
    await create.getByLabel("登录账号", { exact: true }).fill(username);
    await create
      .getByLabel("新密码", { exact: true })
      .fill(
        (
          await fs.readFile(process.env.ADMIN_TEST_PASSWORD_FILE, "utf8")
        ).trim(),
      );
    await create.getByLabel("昵称", { exact: true }).fill("新版控制台验证");
    const [response] = await Promise.all([
      page.waitForResponse(
        (r) =>
          r.url().endsWith("/create/users") && r.request().method() === "POST",
      ),
      create.getByRole("button", { name: "创建记录" }).click(),
    ]);
    expect(response.status()).toBe(200);
    await expect(create).not.toBeVisible();
    await page.getByLabel("搜索当前分类").fill(username);
    await expect(page.locator(".resource-workspace tbody tr")).toHaveCount(1);
    await page.locator(".resource-workspace tbody tr").click();
    await page.getByRole("dialog").getByRole("tab", { name: "编辑" }).click();
    await page
      .getByRole("dialog")
      .getByLabel("昵称", { exact: true })
      .fill("资料保存已验证");
    await page.getByRole("button", { name: "保存修改" }).click();
    await expect(page.locator(".resource-workspace tbody tr")).toContainText(
      "资料保存已验证",
    );
    await page.getByLabel("关闭详情", { exact: true }).click();
  }
  for (const width of [1024, 390]) {
    await page.setViewportSize({ width, height: 844 });
    await nav("用户维度");
    await page.locator(".entity-directory-table tbody tr").first().click();
    await expect(page.locator(".entity-hero")).toBeVisible();
    await snap("user-" + width);
    await noOverflow();
    await nav("角色维度");
    await page.locator(".entity-directory-table tbody tr").first().click();
    await expect(page.locator(".entity-hero")).toBeVisible();
    await snap("character-" + width);
    await noOverflow();
    await page.getByRole("button", { name: "管理资料" }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await noOverflow();
    await snap("drawer-" + width);
    await page.getByLabel("关闭详情", { exact: true }).click();
    await nav("后台数据维度");
    await snap("backend-" + width);
    await noOverflow();
  }
  await nav("角色维度");
  await page.locator(".entity-directory-table tbody tr").first().click();
  await page.reload();
  await expect(page.locator(".entity-hero")).toBeVisible();
  expect(errors).toEqual([]);
  expect(apiErrors).toEqual([]);
  const result = {
    passed: true,
    base,
    paid_calls: 0,
    fixture_writes: writes,
    page_errors: errors,
    api_errors: apiErrors,
    viewports: ["1512×1050", "1024×844", "390×844"],
    checks: [
      "auth",
      "lazy-counts",
      "cursor-pagination",
      "search",
      "structured-fields",
      "user-character-links",
      "scoped-data",
      "AI-profile-editor",
      "management-tools",
      "redacted-credentials",
      "responsive-drawers",
      "hash-reload",
    ],
  };
  await fs.writeFile(
    path.join(output, "result.json"),
    JSON.stringify(result, null, 2),
  );
  console.log(JSON.stringify(result));
} catch (e) {
  await snap("failure");
  throw e;
} finally {
  await browser.close();
}
