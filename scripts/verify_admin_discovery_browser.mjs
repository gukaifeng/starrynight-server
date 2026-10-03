// Explicit local fixtures or read-only acceptance of the deployed console.
import { createRequire } from "node:module";
import fs from "node:fs/promises";
import path from "node:path";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
const require = createRequire(
  new URL("../admin-web/package.json", import.meta.url),
);
const { chromium, expect } = require("@playwright/test");
const base = process.env.ADMIN_TEST_BASE || "http://127.0.0.1:18844";
const fixture = process.env.ADMIN_TEST_DISCOVERY_FIXTURE === "true";
if (fixture && new URL(base).hostname !== "127.0.0.1")
  throw Error("Fixtures require loopback");
const output = process.env.ADMIN_TEST_OUTPUT || ".local/discovery-browser";
await fs.mkdir(output, { recursive: true, mode: 0o700 });
const browser = await chromium.launch({
  executablePath: process.env.CHROME_EXECUTABLE,
  headless: true,
  args: ["--no-proxy-server"],
});
const page = await browser.newPage({ viewport: { width: 1512, height: 1050 } });
const errors = [],
  writes = [];
page.on("pageerror", (e) => errors.push(e.message));
page.on("request", (r) => {
  const u = new URL(r.url());
  if (
    u.pathname.startsWith("/admin-api/") &&
    r.method() !== "GET" &&
    !u.pathname.endsWith("/login")
  )
    writes.push(u.pathname);
});
let denied = false;
const curation = JSON.parse(
  await fs.readFile(
    new URL("../internal/admin/discovery_curation.json", import.meta.url),
    "utf8",
  ),
);
const item = (id, name, language, creator = false) => ({
  id,
  name,
  description: name + "的公开故事",
  creator,
  updated_at: "2026-10-03T00:00:00Z",
  author: { id: "starry-studio", name: "星夜", bio: "认真打磨每一次相遇。" },
  delivery: language === "en" ? "oss" : "bundled",
  download_bytes: 12345,
  release_version: 1,
  data: {
    public_profile: {
      id,
      name,
      invitation: "一起看看今天的新故事。",
      story: name + "的公开故事",
      occupation: language === "en" ? "英语伙伴" : "花店的见习花艺师",
      traits: ["温柔", "好奇"],
      likes: ["花草"],
      world: "星夜小镇",
      tone: "轻柔",
      dialogueLanguage: language,
      scenarios: [
        {
          id: "story",
          title: "慢慢认识",
          subtitle: "一段共同的故事",
          category: "relationship",
        },
      ],
    },
    descriptor: {
      display: { originalName: name },
      actions: [{ button: true, label: "招手" }],
    },
    collection: {
      voices: [{ title: "轻柔", detail: "已有音色" }],
      music: [],
      environments: ["garden"],
    },
    cover_layout: {
      headBounds: { x: 0.19, y: 0.065, width: 0.66, height: 0.49 },
    },
    audition_text: "已有试听",
  },
  media: Object.fromEntries(
    ["cover", "avatar", "audition"].map((kind) => [
      kind,
      {
        url: `/admin-api/v1/discovery/${id}/media/${kind}`,
        size: 3,
        content_type: kind === "audition" ? "audio/wav" : "image/jpeg",
      },
    ]),
  ),
});
const fixtureItems = [
  item("anime-chiffon", "Chiffon", "zh"),
  item("anime-fiona", "Fiona", "en"),
  item("fixture-creator", "新伙伴", "zh", true),
];
async function mock() {
  const artworkRoot = process.env.ADMIN_TEST_ARTWORK_ROOT;
  if (!artworkRoot)
    throw Error(
      "Set an explicit existing artwork package for fixture previews",
    );
  const artwork = JSON.parse(
    await fs.readFile(path.join(artworkRoot, "manifest.json"), "utf8"),
  );
  await page.route("**/admin-api/v1/**", async (route) => {
    const u = new URL(route.request().url()),
      p = u.pathname;
    if (p.includes("/media/")) {
      const kind = p.split("/").at(-1);
      if (kind === "audition") {
        const wave = Buffer.alloc(44 + 16000);
        wave.write("RIFF");
        wave.writeUInt32LE(wave.length - 8, 4);
        wave.write("WAVEfmt ", 8);
        wave.writeUInt32LE(16, 16);
        wave.writeUInt16LE(1, 20);
        wave.writeUInt16LE(1, 22);
        wave.writeUInt32LE(8000, 24);
        wave.writeUInt32LE(16000, 28);
        wave.writeUInt16LE(2, 32);
        wave.writeUInt16LE(16, 34);
        wave.write("data", 36);
        wave.writeUInt32LE(16000, 40);
        await route.fulfill({ contentType: "audio/wav", body: wave });
        return;
      }
      const id = p.includes("anime-fiona") ? "anime-fiona" : "anime-chiffon";
      await route.fulfill({
        contentType: "image/jpeg",
        body: await fs.readFile(
          path.join(artworkRoot, artwork.characters[id][kind].path),
        ),
      });
      return;
    }
    let data;
    if (p.endsWith("/session"))
      data = {
        user: { id: "fixture-owner", username: "owner", role: "owner" },
        csrf: "fixture",
      };
    else if (p.endsWith("/resources")) data = [];
    else if (p.endsWith("/discovery"))
      data = { items: fixtureItems, curation, complete: true, platform: "ios" };
    else if (p.endsWith("/objects")) {
      if (denied) {
        await route.fulfill({
          status: 422,
          contentType: "application/json",
          body: JSON.stringify({
            error: "OSS 列表不可用，请检查存储配置与授权",
          }),
        });
        return;
      }
      const prefix = u.searchParams.get("prefix") || "",
        after = u.searchParams.get("after"),
        folders = u.searchParams.get("folders") === "true",
        key = u.searchParams.get("key");
      const objectKey = after ? "characters/b.json" : "characters/a.json";
      data = {
        configured: true,
        bucket: "fixture-bucket",
        prefix,
        directories: folders && !prefix ? ["characters/"] : [],
        items:
          !folders || prefix
            ? [
                {
                  key: objectKey,
                  bytes: 123,
                  modified: "2026-10-03T00:00:00Z",
                  etag: "fixture",
                  storage_class: "Standard",
                },
              ]
            : [],
        next: (!folders || prefix) && !after ? "a+b/=" : "",
        detail: key
          ? {
              key,
              bytes: 123,
              content_type: "application/json",
              metadata: { sha256: "fixture-sha" },
              references: [
                {
                  character_id: "anime-chiffon",
                  kind: "marketplace",
                  enabled: true,
                },
              ],
            }
          : null,
      };
    } else if (p.endsWith("/objects/detail")) {
      await new Promise((resolve) => setTimeout(resolve, 150));
      data = {
        key: u.searchParams.get("key"),
        bytes: 123,
        content_type: "application/json",
        metadata: { sha256: "fixture-sha" },
        references: [
          { character_id: "anime-chiffon", kind: "marketplace", enabled: true },
        ],
      };
    } else if (p.endsWith("/objects/download"))
      data = { schema_version: 1, name: "Fixture object" };
    else data = {};
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(data),
    });
  });
}
async function snap(name) {
  await page.screenshot({
    path: path.join(output, name + ".png"),
    fullPage: true,
    animations: "disabled",
  });
}
async function noOverflow() {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
  ).toBe(false);
}
try {
  if (fixture) await mock();
  await page.goto(base + "/#discovery");
  if (!fixture) {
    await expect(
      page.getByRole("heading", { name: "管理员登录" }),
    ).toBeVisible();
    const unauth = await page.evaluate(
      async () => (await fetch("/admin-api/v1/discovery")).status,
    );
    expect(unauth).toBe(401);
    await page
      .getByLabel("账号", { exact: true })
      .fill(process.env.ADMIN_TEST_USERNAME || "owner");
    await page
      .getByLabel("密码", { exact: true })
      .fill(
        (
          await fs.readFile(process.env.ADMIN_TEST_PASSWORD_FILE, "utf8")
        ).trim(),
      );
    await page.getByRole("button", { name: "登录控制台" }).click();
  }
  await expect(
    page.getByRole("heading", { name: "发现", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".discover-card").first()).toBeVisible({
    timeout: 25000,
  });
  const report = fixture
    ? { items: fixtureItems }
    : await page.evaluate(async () =>
        (await fetch("/admin-api/v1/discovery")).json(),
      );
  const fullCount = report.items.length;
  await expect(page.locator(".discover-card")).toHaveCount(fullCount);
  if (!fixture) {
    // Compare published definitions to the same API consumed by iPhone.
    const publicReport = [];
    let after = "";
    do {
      // Keep the console's same-origin CSP intact. The test harness reads the
      // public App API independently; financial/authentication data is absent.
      const { stdout } = await promisify(execFile)(
        "curl",
        [
          "--noproxy",
          "*",
          "--connect-timeout",
          "10",
          "--max-time",
          "30",
          "-fsS",
          "https://39.105.116.74:8443/v1/store/characters?limit=200&platform=ios&after=" +
            encodeURIComponent(after),
        ],
        { maxBuffer: 16 * 1024 * 1024 },
      );
      const result = JSON.parse(stdout);
      publicReport.push(...result.items);
      after = result.next || "";
    } while (after);
    const publicByID = new Map(publicReport.map((item) => [item.id, item]));
    for (const item of report.items.filter((item) => !item.creator)) {
      const original = publicByID.get(item.id);
      expect(Boolean(original)).toBe(true);
      expect(item.name).toBe(original.name);
      expect(item.description).toBe(original.description);
      expect(item.data).toEqual(original.data);
      expect(Object.keys(item.media)).toEqual(
        Object.keys(original.media).filter((kind) =>
          ["cover", "avatar", "audition", "video"].includes(kind),
        ),
      );
    }
  }
  // Visit each card so below-fold lazy covers are actually requested. A cold
  // browser should exercise the same scroll-to-load behavior as a person.
  for (const card of await page.locator(".discover-card").all()) {
    await card.scrollIntoViewIfNeeded();
    await expect
      .poll(
        () =>
          card.locator("img").evaluateAll(
            (images) =>
              images.filter((image) => image.complete && image.naturalWidth > 0)
                .length,
          ),
        { timeout: 30000 },
      )
      .toBe(1);
  }
  await page.locator(".discover-card").first().scrollIntoViewIfNeeded();
  await noOverflow();
  await snap("discovery-desktop");
  await page.getByLabel("搜索发现内容").fill("Fiona");
  await expect(page.locator(".discover-card")).toHaveCount(1);
  await page
    .getByRole("button", { name: "查看Fiona的资料", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("英语");
  await expect(dialog.locator("audio")).toHaveCount(1);
  expect(
    await dialog.evaluate((element) => {
      const cover = element
        .querySelector(".discover-cover")
        .getBoundingClientRect();
      const identity = element
        .querySelector(".discover-identity")
        .getBoundingClientRect();
      return cover.bottom <= identity.top;
    }),
  ).toBe(true);
  expect(await dialog.locator("audio").getAttribute("preload")).toBe("none");
  await dialog.getByText("模型与资源信息", { exact: true }).click();
  await expect(dialog).toContainText("发布版本");
  await snap("character-details-desktop");
  await page.getByRole("button", { name: "关闭角色资料" }).click();
  await page.getByRole("button", { name: "清除搜索" }).click();
  await page
    .locator(".discover-categories")
    .getByRole("button", { name: "英语", exact: true })
    .click();
  const englishCount = report.items.filter(
    (item) => item.data.public_profile?.dialogueLanguage === "en",
  ).length;
  await expect(page.locator(".discover-card")).toHaveCount(englishCount);
  await page
    .locator(".discover-categories")
    .getByRole("button", { name: "全部", exact: true })
    .click();
  await page.getByRole("tab", { name: "用户作品", exact: true }).click();
  await expect(page.locator(".discover-card")).toHaveCount(
    report.items.filter((item) => item.creator).length,
  );
  if (!report.items.some((item) => item.creator))
    await page.getByRole("button", { name: "看看全部角色" }).click();
  else await page.getByRole("tab", { name: "全部", exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await noOverflow();
  await snap("discovery-mobile");
  await page.locator(".discover-card").first().click();
  await snap("character-details-mobile");
  await page.getByRole("button", { name: "关闭角色资料" }).click();
  await page.setViewportSize({ width: 1512, height: 1050 });
  await page.getByRole("button", { name: "OSS Bucket", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "OSS Bucket", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".oss-file-list")).toBeVisible({ timeout: 25000 });
  await noOverflow();
  await snap("oss-root-desktop");
  const directories = page.getByRole("button", { name: /^打开目录 / });
  if (await directories.count()) {
    await directories.first().click();
    await expect(
      page.getByRole("button", { name: "上一级目录", exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: "上一级目录", exact: true }).click();
    await expect(page.getByLabel("OSS 路径前缀")).toHaveValue("");
  }
  await page.getByRole("button", { name: "全部对象", exact: true }).click();
  await expect(
    page.getByRole("button", { name: /^查看文件 / }).first(),
  ).toBeVisible({ timeout: 25000 });
  if (
    await page.getByRole("button", { name: "下一页", exact: true }).isEnabled()
  ) {
    await page.getByRole("button", { name: "下一页", exact: true }).click();
    await expect(page.locator(".oss-file-list .pagination")).toContainText(
      "第 2 页",
    );
    await page.getByRole("button", { name: "上一页", exact: true }).click();
    await expect(page.locator(".oss-file-list .pagination")).toContainText(
      "第 1 页",
    );
  }
  const files = page.getByRole("button", { name: /^查看文件 / });
  await files.first().click();
  await expect(page.locator(".oss-file-list")).toBeVisible();
  await expect(page.locator(".oss-object-detail")).toContainText("文件类型", {
    timeout: 25000,
  });
  await expect(page.locator(".oss-object-detail")).toContainText(
    "角色资源引用",
    { timeout: 25000 },
  );
  await expect(
    page.locator(".oss-object-detail").getByRole("link", { name: "下载文件" }),
  ).toHaveAttribute("href", /\/objects\/download\?key=/);
  if (fixture) {
    await page.getByRole("button", { name: "预览文件", exact: true }).click();
    await expect(page.locator(".oss-object-detail")).toContainText(
      "Fixture object",
    );
  }
  await noOverflow();
  await snap("oss-file-desktop");
  await page.setViewportSize({ width: 390, height: 844 });
  await noOverflow();
  await snap("oss-file-mobile");
  await page.getByLabel("OSS 路径前缀").fill("characters/");
  await page.getByRole("button", { name: "查找", exact: true }).click();
  await expect(page.locator(".oss-file-list .pagination")).toContainText(
    "第 1 页",
  );
  await expect(
    page.getByRole("button", { name: "关闭文件详情", exact: true }),
  ).toHaveCount(0);
  if (fixture) {
    denied = true;
    await page.getByRole("button", { name: "刷新", exact: true }).click();
    await expect(
      page.getByText("OSS 列表不可用，请检查存储配置与授权", { exact: true }),
    ).toBeVisible();
  }
  expect(errors).toEqual([]);
  expect(writes).toEqual([]);
  await fs.writeFile(
    path.join(output, "result.json"),
    JSON.stringify(
      {
        verified: true,
        fixture,
        catalogue_count: fullCount,
        browser_errors: errors,
        resource_writes: writes,
        checked: [
          "authentication",
          "all_catalogue_items",
          "existing_covers",
          "public_metadata_parity",
          "search",
          "categories",
          "creator_shelf",
          "details",
          "audition_no_autoplay",
          "desktop",
          "mobile",
          "oss_root",
          "directories",
          "prefix",
          "pagination",
          "head_metadata",
          "download_link",
          "references",
          ...(fixture ? ["json_preview", "oss_permission_error"] : []),
        ],
      },
      null,
      2,
    ),
  );
  console.log(
    JSON.stringify({
      verified: true,
      fixture,
      catalogue_count: fullCount,
      output,
    }),
  );
} finally {
  await browser.close();
}
