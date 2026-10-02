// Real authenticated browser checks; captures and synthetic fixtures stay private.
import { createRequire } from "node:module";
import fs from "node:fs/promises";
import path from "node:path";
const require = createRequire(
  new URL("../admin-web/package.json", import.meta.url),
);
const { chromium, expect } = require("@playwright/test");
const base = process.env.ADMIN_TEST_BASE ?? "http://127.0.0.1:18100";
const output =
  process.env.ADMIN_TEST_OUTPUT ?? ".local/admin-management-verification";
await fs.mkdir(output, { recursive: true });
const browser = await chromium.launch({
  executablePath: process.env.CHROME_EXECUTABLE,
  headless: true,
  args: [
    "--enable-unsafe-swiftshader",
    ...(process.env.ADMIN_TEST_DIRECT === "true" ? ["--no-proxy-server"] : []),
  ],
});
const context = await browser.newContext({
  viewport: { width: 1512, height: 1050 },
});
const page = await context.newPage();
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
try {
  await page.goto(base);
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
  await expect(
    page.getByRole("heading", { name: "服务与数据总览" }),
  ).toBeVisible();
  const checked = [];
  for (const name of [
    "资源与模型",
    "声音文件",
    "会话与缓存",
    "备份与恢复",
    "运行配置",
    "版本与证书",
    "服务器文件",
    "维护任务",
  ]) {
    const endpoint = {
      资源与模型: "/runtime/library",
      声音文件: "/files/ai",
      会话与缓存: "/cache",
      备份与恢复: "/runtime/backups",
      运行配置: "/runtime/config",
      版本与证书: "/runtime/releases",
      服务器文件: "/runtime/files",
      维护任务: "/runtime/jobs",
    }[name];
    const [response] = await Promise.all([
      page.waitForResponse(
        (r) =>
          r.url().includes("/admin-api/v1" + endpoint) &&
          r.request().method() === "GET",
      ),
      nav(name).click(),
    ]);
    expect(response.status()).toBe(200);
    await response.json();
    await expect(
      page.getByRole("heading", { name, exact: true }),
    ).toBeVisible();
    await expect(page.locator(".management-workspace .error-note")).toHaveCount(
      0,
    );
    checked.push(name);
    if (["运行配置", "声音文件", "备份与恢复"].includes(name))
      await page.screenshot({
        path: path.join(output, name + "-desktop.png"),
        fullPage: true,
        animations: "disabled",
      });
  }
  await nav("声音文件").click();
  await expect(page.locator(".management-list tbody tr").first()).toBeVisible();
  await page.locator(".management-list tbody tr").first().click();
  await expect(page.locator("audio")).toBeVisible();
  const sound = await page.locator("audio").getAttribute("src");
  const audio = await page.evaluate(async (url) => {
    const response = await fetch(url);
    const bytes = new Uint8Array(await response.arrayBuffer());
    return {
      status: response.status,
      header: String.fromCharCode(...bytes.slice(0, 4)),
    };
  }, sound);
  expect(audio.status).toBe(200);
  expect(audio.header).toBe("RIFF");
  await page.screenshot({
    path: path.join(output, "audio-detail-desktop.png"),
    fullPage: true,
    animations: "disabled",
  });
  if (process.env.ADMIN_TEST_MUTATIONS === "true") {
    await page.getByRole("button", { name: "移除文件", exact: true }).click();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "确认操作" })
      .click();
    await expect(page.getByRole("dialog")).not.toBeVisible();
    await page.getByRole("button", { name: "回收站", exact: true }).click();
    await expect(
      page.locator(".management-list tbody tr").first(),
    ).toBeVisible();
    await page.locator(".management-list tbody tr").first().click();
    await page.getByRole("button", { name: "恢复文件", exact: true }).click();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "确认操作" })
      .click();
    await expect(page.getByRole("dialog")).not.toBeVisible();
    await nav("资源与模型").click();
    await page
      .getByLabel("上传资源文件", { exact: true })
      .setInputFiles(".local/preview-fixture.glb");
    await expect(
      page.locator(".management-list tbody tr").first(),
    ).toBeVisible();
    await page.locator(".management-list tbody tr").first().click();
    await expect(page.getByText("1 网格", { exact: true })).toBeVisible({
      timeout: 30000,
    });
    await expect(page.locator(".model-canvas canvas")).toBeVisible();
    await page.screenshot({
      path: path.join(output, "model-preview-desktop.png"),
      fullPage: true,
      animations: "disabled",
    });
    await page
      .getByLabel("上传资源文件", { exact: true })
      .setInputFiles({
        name: "fixture-inspection.json",
        mimeType: "application/json",
        buffer: Buffer.from(
          JSON.stringify({
            capability: "fixture-json-preview",
            api_key: "FORGED_PRIVATE_SECRET",
          }),
        ),
      });
    await page
      .locator(".management-list tbody tr")
      .filter({ hasText: "fixture-inspection.json" })
      .click();
    await expect(page.locator(".management-detail pre").first()).toContainText(
      "fixture-json-preview",
    );
    await expect(page.locator(".management-detail")).not.toContainText(
      "FORGED_PRIVATE_SECRET",
    );
  }
  await nav("运行配置").click();
  await expect(
    page.getByLabel("百炼 API Key", { exact: true }),
  ).toHaveAttribute("type", "password");
  expect(
    await page.getByLabel("百炼 API Key", { exact: true }).inputValue(),
  ).toBe("");
  await expect(
    page.getByLabel("OSS AccessKey Secret", { exact: true }),
  ).toHaveAttribute("type", "password");
  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(() =>
      page
        .locator(".sidebar")
        .evaluate((el) => el.getBoundingClientRect().right),
    )
    .toBeLessThanOrEqual(1);
  await page.screenshot({
    path: path.join(output, "configuration-mobile.png"),
    fullPage: true,
    animations: "disabled",
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
  ).toBe(false);
  await page.getByRole("button", { name: "打开导航" }).click();
  await nav("声音文件").click();
  await page.locator(".management-list tbody tr").first().click();
  await page.screenshot({
    path: path.join(output, "audio-detail-mobile.png"),
    fullPage: true,
    animations: "disabled",
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
  ).toBe(false);
  expect(errors).toEqual([]);
  const result = {
    passed: true,
    base,
    checked,
    audio_wav_verified: true,
    page_errors: errors,
    paid_calls: 0,
    viewports: ["1512×1050", "390×844"],
  };
  await fs.writeFile(
    path.join(output, "result.json"),
    JSON.stringify(result, null, 2),
  );
  console.log(JSON.stringify(result));
} finally {
  await browser.close();
}
