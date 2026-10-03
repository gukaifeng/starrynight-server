import { object, text } from "./ConsoleUI";
import type { Row } from "./api";

export type DiscoveryItem = {
  id: string;
  name: string;
  description: string;
  data: Row;
  media: Record<string, { url: string; size: number; content_type: string }>;
  author: { id: string; name: string; bio: string };
  creator: boolean;
  updated_at: string;
  base_id?: string;
  delivery: string;
  download_bytes: number;
  release_version: number;
};
export type Curation = {
  schemaVersion: number;
  characters: Record<
    string,
    { categories: string[]; featured: boolean; rank: number }
  >;
};
export type DiscoveryReport = {
  items: DiscoveryItem[];
  curation: Curation;
  complete: boolean;
  platform: string;
};
export const profileOf = (item: DiscoveryItem) =>
  object(item.data.public_profile);
export const descriptorOf = (item: DiscoveryItem) =>
  object(item.data.descriptor);
export const displayOf = (item: DiscoveryItem) =>
  object(descriptorOf(item).display);
export const strings = (value: unknown): string[] =>
  Array.isArray(value)
    ? value.filter((v): v is string => typeof v === "string")
    : [];
export const scenariosOf = (item: DiscoveryItem): Row[] =>
  Array.isArray(profileOf(item).scenarios)
    ? (profileOf(item).scenarios as Row[])
    : [];
export const nameOf = (item: DiscoveryItem) =>
  (item.creator ? item.name : text(profileOf(item).name)) || item.name;
export const invitationOf = (item: DiscoveryItem) =>
  text(profileOf(item).invitation) || text(displayOf(item).invitation);

// Match CharacterMarketplace's catalogue categories and recommendation order.
export function categoriesOf(
  item: DiscoveryItem,
  curation: Curation,
): string[] {
  const metadata = item.creator ? undefined : curation.characters[item.id];
  const profile = profileOf(item),
    routes = scenariosOf(item);
  const extra =
    profile.dialogueLanguage === "en"
      ? ["英语"]
      : routes.some((r) => /恋爱|约会/.test(text(r.category)))
        ? ["恋爱"]
        : routes.length
          ? ["剧情"]
          : [];
  return [...new Set([...(metadata?.categories ?? ["日常"]), ...extra])].sort();
}
export function catalogueCategories(
  items: DiscoveryItem[],
  curation: Curation,
) {
  const available = new Set(
    items.flatMap((item) => categoriesOf(item, curation)),
  );
  const preferred = [
    "恋爱",
    "英语",
    "剧情",
    "日常",
    "治愈",
    "元气",
    "校园",
    "幻想",
  ];
  return [
    "全部",
    ...preferred.filter((c) => available.has(c)),
    ...[...available].filter((c) => !preferred.includes(c)).sort(),
  ];
}
const fold = (value: string) =>
  value.normalize("NFKD").replace(/\p{M}/gu, "").toLocaleLowerCase();
export function discoveryResults(
  items: DiscoveryItem[],
  curation: Curation,
  query: string,
  shelf: string,
  category: string,
  sort: string,
) {
  const terms = fold(query).trim().split(/\s+/).filter(Boolean);
  return items
    .filter((item) => {
      const profile = profileOf(item),
        display = displayOf(item),
        categories = categoriesOf(item, curation);
      const haystack = fold(
        [
          nameOf(item),
          item.description,
          text(display.originalName),
          text(display.tagline),
          text(profile.story),
          text(profile.tone),
          text(profile.occupation),
          item.author.name,
          ...strings(profile.traits),
          ...categories,
          ...scenariosOf(item).map((r) => text(r.title)),
        ].join(" "),
      );
      return (
        (shelf !== "creators" || item.creator) &&
        (category === "全部" || categories.includes(category)) &&
        terms.every((term) => haystack.includes(term))
      );
    })
    .sort((a, b) => {
      if (sort === "name") {
        const order = nameOf(a).localeCompare(nameOf(b), "zh-CN", {
          numeric: true,
          sensitivity: "base",
        });
        if (order) return order;
      } else if (sort === "updated") {
        // Built-in characters have distantPast in the App, not publication time.
        const difference =
          (b.creator ? Date.parse(b.updated_at) || 0 : 0) -
          (a.creator ? Date.parse(a.updated_at) || 0 : 0);
        if (difference) return difference;
      } else {
        const rank = (item: DiscoveryItem) =>
          !item.creator ? (curation.characters[item.id]?.rank ?? 1000) : 1000;
        const difference = rank(a) - rank(b);
        if (difference) return difference;
      }
      return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
    });
}

export type HeadBounds = {
  x: number;
  y: number;
  width: number;
  height: number;
};
// Same portrait aperture and focal calculation as CharacterArtworkLayout.frame.
export function coverFrame(
  sw: number,
  sh: number,
  tw: number,
  th: number,
  head: HeadBounds,
) {
  const box = {
    x: head.x * sw,
    y: head.y * sh,
    width: head.width * sw,
    height: head.height * sh,
  };
  if (
    ![sw, sh, tw, th, box.width, box.height].every(
      (v) => Number.isFinite(v) && v > 0,
    )
  )
    return null;
  const scale = Math.max(
    Math.max(tw / sw, th / sh),
    Math.min((tw * 0.92) / box.width, (th * 0.64) / box.height),
  );
  const width = sw * scale,
    height = sh * scale,
    headHeight = box.height * scale;
  const centerY =
    headHeight > th * 0.92
      ? th * 0.53 - headHeight * 0.12
      : th * 0.055 + headHeight / 2;
  return {
    width,
    height,
    left: Math.min(
      0,
      Math.max(tw - width, tw / 2 - (box.x + box.width / 2) * scale),
    ),
    top: Math.min(
      0,
      Math.max(th - height, centerY - (box.y + box.height / 2) * scale),
    ),
  };
}
