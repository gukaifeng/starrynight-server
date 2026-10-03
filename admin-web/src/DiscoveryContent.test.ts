import { describe, expect, it } from "vitest";
import {
  catalogueCategories,
  categoriesOf,
  coverFrame,
  discoveryResults,
  type Curation,
  type DiscoveryItem,
} from "./DiscoveryContent";

const curation: Curation = {
  schemaVersion: 1,
  characters: {
    fiona: { categories: ["角色"], featured: false, rank: 10 },
    ichigo: { categories: ["角色"], featured: false, rank: 20 },
  },
};
const make = (
  id: string,
  profile: object = {},
  extra: Partial<DiscoveryItem> = {},
): DiscoveryItem => ({
  id,
  name: id,
  description: "",
  data: { public_profile: profile },
  media: {},
  author: { id: "starry", name: "星夜", bio: "" },
  creator: false,
  updated_at: "2026-10-03",
  delivery: "bundled",
  download_bytes: 0,
  release_version: 0,
  ...extra,
});
const items = [
  make("ichigo", {
    scenarios: [{ title: "打烊后的石桥", category: "心动约会" }],
  }),
  make("fiona", {
    dialogueLanguage: "en",
    occupation: "英语伙伴",
    scenarios: [{ title: "Get to know me", category: "relationship" }],
  }),
  make("creator", {}, { creator: true }),
];
describe("App discovery content parity", () => {
  it("matches language and scenario category rules, including creator defaults", () => {
    expect(categoriesOf(items[0], curation)).toEqual(["恋爱", "角色"]);
    expect(categoriesOf(items[1], curation)).toEqual(["英语", "角色"]);
    expect(categoriesOf(items[2], curation)).toEqual(["日常"]);
    expect(catalogueCategories(items, curation)).toEqual([
      "全部",
      "恋爱",
      "英语",
      "日常",
      "角色",
    ]);
  });
  it("combines shelf, category and multiword public-field search", () => {
    expect(
      discoveryResults(
        items,
        curation,
        "星夜 英语",
        "all",
        "英语",
        "recommended",
      ).map((i) => i.id),
    ).toEqual(["fiona"]);
    expect(
      discoveryResults(
        items,
        curation,
        "石桥",
        "all",
        "恋爱",
        "recommended",
      ).map((i) => i.id),
    ).toEqual(["ichigo"]);
    expect(
      discoveryResults(
        items,
        curation,
        "",
        "creators",
        "全部",
        "recommended",
      ).map((i) => i.id),
    ).toEqual(["creator"]);
  });
  it("preserves App recommendation rank and doesn't treat built-in publication as an update", () => {
    expect(
      discoveryResults(items, curation, "", "all", "全部", "recommended").map(
        (i) => i.id,
      ),
    ).toEqual(["fiona", "ichigo", "creator"]);
    expect(
      discoveryResults(items, curation, "", "all", "全部", "updated").map(
        (i) => i.id,
      ),
    ).toEqual(["creator", "fiona", "ichigo"]);
  });
  it("uses the same focal rectangle at desktop and phone sizes without uncovered edges", () => {
    for (const width of [160, 240, 360]) {
      const height = width / 0.94;
      const frame = coverFrame(800, 1200, width, height, {
        x: 0.19,
        y: 0.065,
        width: 0.66,
        height: 0.49,
      })!;
      expect(frame.width).toBeGreaterThanOrEqual(width);
      expect(frame.height).toBeGreaterThanOrEqual(height);
      expect(frame.left).toBeLessThanOrEqual(0);
      expect(frame.top).toBeLessThanOrEqual(0);
      expect(frame.left + frame.width).toBeGreaterThanOrEqual(width - 0.000001);
      expect(frame.top + frame.height).toBeGreaterThanOrEqual(
        height - 0.000001,
      );
    }
    expect(
      coverFrame(0, 0, 200, 200, { x: 0, y: 0, width: 0, height: 0 }),
    ).toBeNull();
  });
});
