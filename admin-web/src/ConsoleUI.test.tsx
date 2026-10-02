import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { scalar, StructuredData } from "./ConsoleUI";
describe("heterogeneous management records", () => {
  it("keeps false, zero, missing and nested values distinct without JSON blobs", () => {
    const html = renderToStaticMarkup(
      <StructuredData
        value={{
          guest: false,
          version: 0,
          profile: { display_name: "星夜", bio: "第一行\n第二行" },
          goal_progress: {
            bond: { trust: 36.5 },
            branches: [{ name: "共同学习", paused: false }],
          },
          extra: null,
        }}
      />,
    );
    expect(html).toContain("访客账号");
    expect(html).toContain(">否<");
    expect(html).toContain(">0<");
    expect(html).toContain("共同学习");
    expect(html).toContain("36.5");
    expect(html).toContain("未设置");
    expect(html).not.toContain("[object Object]");
    expect(html).not.toContain("<pre");
  });
  it("formats SQLite seconds and PostgreSQL timestamps as dates", () => {
    expect(scalar(1700000000, "created")).not.toBe("1700000000");
    expect(scalar("2026-10-03T01:00:00Z", "updated_at")).not.toContain("T01:");
    expect(scalar(0, "version")).toBe("0");
  });
  it("preserves arrays, unknown extension fields and untrusted text safely", () => {
    const html = renderToStaticMarkup(
      <StructuredData
        value={{
          extensions: {
            future: { items: ["<script>alert(1)</script>", "第二项"] },
          },
        }}
      />,
    );
    expect(html).toContain("future");
    expect(html).toContain("第二项");
    expect(html).toContain("&lt;script&gt;");
    expect(html).not.toContain("<script>");
    expect(scalar({ future: 1 })).toBe("1 个字段");
  });
});
