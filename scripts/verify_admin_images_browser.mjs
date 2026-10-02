// Authenticated image verification; artwork and captures remain private.
import { createRequire } from "node:module";
import fs from "node:fs/promises";
import path from "node:path";
const require = createRequire(
  new URL("../admin-web/package.json", import.meta.url),
);
const { chromium, expect } = require("@playwright/test");
const base = process.env.ADMIN_TEST_BASE ?? "http://127.0.0.1:18100";
const output =
  process.env.ADMIN_TEST_OUTPUT ?? ".local/admin-image-verification";
await fs.mkdir(output, { recursive: true });
const browser = await chromium.launch({
  executablePath: process.env.CHROME_EXECUTABLE,
  headless: true,
  args: process.env.ADMIN_TEST_DIRECT === "true" ? ["--no-proxy-server"] : [],
});
const page = await browser.newPage({ viewport: { width: 1512, height: 1050 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
const nav = (name) => ({
  click: async () => {
    const response = await page.evaluate(async () => {
      const lists = await Promise.all([
        fetch("/admin-api/v1/resources").then((r) => r.json()),
        fetch("/admin-api/v1/ai/console/resources").then((r) => r.json()),
      ]);
      return [...lists[0], ...lists[1].map((r) => ({ ...r, ai: true }))];
    });
    const resource = response.find((r) => r.name === name);
    const tools = {
      总览: "overview",
      资源与模型: "manage:library",
      声音文件: "manage:audio",
      会话与缓存: "manage:cache",
      备份与恢复: "manage:backups",
      运行配置: "manage:config",
      版本与证书: "manage:releases",
      服务器文件: "manage:files",
      维护任务: "manage:jobs",
    };
    const view = resource
      ? (resource.ai ? "ai:" : "") + resource.id
      : tools[name];
    if (!view) throw Error("Unknown console destination: " + name);
    await page.evaluate((view) => {
      location.hash = encodeURIComponent(view);
    }, view);
  },
});
async function call(endpoint) {
  return page.evaluate(async (endpoint) => {
    const response = await fetch("/admin-api/v1" + endpoint);
    return { status: response.status, data: await response.json() };
  }, endpoint);
}
async function readyImage(locator) {
  await expect(locator).toBeVisible();
  await expect
    .poll(() =>
      locator.evaluate((image) => image.complete && image.naturalWidth > 0),
    )
    .toBe(true);
}
try {
  await page.goto(base);
  expect(
    (await call("/record-images/character/anime-kipfel/avatar")).status,
  ).toBe(401);
  await page
    .getByLabel("账号", { exact: true })
    .fill(process.env.ADMIN_TEST_USERNAME ?? "owner");
  await page
    .getByLabel("密码", { exact: true })
    .fill(
      (await fs.readFile(process.env.ADMIN_TEST_PASSWORD_FILE, "utf8")).trim(),
    );
  await page.getByRole("button", { name: "登录控制台" }).click();
  await page
    .locator(".sidebar")
    .getByRole("button", { name: "后台数据维度", exact: true })
    .click();
  await page
    .locator(".sidebar")
    .getByRole("button", { name: "总览", exact: true })
    .click();
  await page.getByRole("heading", { name: "服务与数据总览" }).waitFor();
  if (process.env.ADMIN_TEST_CREATE_FIXTURE === "true") {
    if (new URL(base).hostname !== "127.0.0.1")
      throw new Error(
        "Fixture creation is restricted to the isolated local server",
      );
    const session = await call("/session");
    const result = await page.evaluate(async (csrf) => {
      const response = await fetch("/admin-api/v1/create/users", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
        body: JSON.stringify({
          username: "artwork_" + Date.now(),
          password: crypto.randomUUID(),
          display_name: "图片验证账户",
        }),
      });
      return { status: response.status, data: await response.json() };
    }, session.data.csrf);
    expect(result.status).toBe(200);
    await fs.writeFile(
      path.join(output, "fixture-user-id.txt"),
      result.data.result.id,
      { mode: 0o600 },
    );
  }
  await nav("角色目录").click();
  await page.locator("tbody tr").first().waitFor();
  await readyImage(page.locator("tbody .record-avatar img").first());
  await page.locator("tbody tr").first().click();
  await readyImage(page.locator(".record-artwork.cover img"));
  await readyImage(page.locator(".record-artwork.avatar img"));
  await page.screenshot({
    path: path.join(output, "character-images-desktop.png"),
    fullPage: true,
    animations: "disabled",
  });
  await page.getByRole("button", { name: "放大查看角色封面" }).click();
  await readyImage(page.locator(".image-original"));
  await page.screenshot({
    path: path.join(output, "cover-preview-desktop.png"),
    fullPage: true,
    animations: "disabled",
  });
  await page.keyboard.press("Escape");
  await expect(page.locator(".image-dialog-panel")).not.toBeVisible();
  await page
    .locator(".detail-panel")
    .getByRole("button", { name: "关闭详情" })
    .click();
  const users = await call("/resources/users");
  expect(users.status).toBe(200);
  await nav("用户账户").click();
  if (users.data.items.length) {
    await page.locator("tbody tr").first().waitFor();
    await readyImage(page.locator("tbody .record-avatar img").first());
    await page.locator("tbody tr").first().click();
    await readyImage(page.locator(".record-artwork.avatar img"));
    await page.screenshot({
      path: path.join(output, "user-images-desktop.png"),
      fullPage: true,
      animations: "disabled",
    });
    await page
      .locator(".detail-panel")
      .getByRole("button", { name: "关闭详情" })
      .click();
  }
  await nav("作者").click();
  await page.locator("tbody tr").first().waitFor();
  await readyImage(page.locator("tbody .record-avatar img").first());
  await nav("AI 角色设定").click();
  await page.locator("tbody tr").first().waitFor();
  await readyImage(page.locator("tbody .record-avatar img").first());
  const catalog = await call("/resources/characters");
  expect(catalog.status).toBe(200);
  const checked = [];
  for (const row of catalog.data.items) {
    for (const variant of ["avatar", "cover"]) {
      const result = await page.evaluate(
        async ({ id, variant }) => {
          const response = await fetch(
            "/admin-api/v1/record-images/character/" +
              encodeURIComponent(id) +
              "/" +
              variant,
          );
          const type = response.headers.get("Content-Type");
          if (response.status !== 200) return { status: response.status, type };
          const image = await createImageBitmap(await response.blob());
          const result = {
            status: response.status,
            type,
            width: image.width,
            height: image.height,
          };
          image.close();
          return result;
        },
        { id: row.id, variant },
      );
      expect(result.status).toBe(200);
      expect(result.width).toBeGreaterThan(0);
      checked.push({ id: row.id, variant, ...result });
    }
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(() =>
      page
        .locator(".sidebar")
        .evaluate((el) => el.getBoundingClientRect().right),
    )
    .toBeLessThanOrEqual(1);
  await page.getByRole("button", { name: "打开导航" }).click();
  await nav("角色目录").click();
  await page.locator("tbody tr").first().click();
  await readyImage(page.locator(".record-artwork.cover img"));
  await page.screenshot({
    path: path.join(output, "character-images-mobile.png"),
    fullPage: true,
    animations: "disabled",
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
  ).toBe(false);
  await page.getByRole("button", { name: "放大查看头像" }).click();
  await readyImage(page.locator(".image-original"));
  await page.getByRole("button", { name: "关闭图片预览" }).click();
  await expect(page.locator(".image-dialog-panel")).not.toBeVisible();
  expect(errors).toEqual([]);
  const report = {
    passed: true,
    paid_calls: 0,
    checked_images: checked.length,
    characters: catalog.data.items.length,
    page_errors: errors,
    viewports: ["1512×1050", "390×844"],
  };
  await fs.writeFile(
    path.join(output, "result.json"),
    JSON.stringify(report, null, 2),
  );
  console.log(JSON.stringify(report));
} finally {
  await browser.close();
}
