export type AdminUser = {
  id: string;
  username: string;
  role: "owner" | "editor" | "viewer";
};
export type Resource = {
  id: string;
  name: string;
  group: string;
  description: string;
  keys: string[];
  fields: string[];
  edit: string[] | null;
  actions: string[] | null;
  ai?: boolean;
};
export type Row = Record<string, unknown>;
export type Page = { items: Row[]; next: string };
let csrf = "";
export const setCSRF = (value: string) => {
  csrf = value;
};
export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch("/admin-api/v1" + path, {
    ...options,
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": csrf,
      ...options.headers,
    },
  });
  const data = await response
    .json()
    .catch(() => ({ error: "服务暂不可用，请稍后重试" }));
  if (
    response.status === 401 &&
    path !== "/login" &&
    typeof window !== "undefined"
  )
    window.dispatchEvent(new Event("admin-session-expired"));
  if (!response.ok)
    throw new Error(
      typeof data.error === "string"
        ? data.error
        : typeof data.detail === "string"
          ? data.detail
          : `操作失败 (${response.status})`,
    );
  return data;
}
export function resourcePath(r: Resource) {
  return (r.ai ? "/ai/console" : "") + "/resources/" + r.id;
}
export function keysOf(r: Resource, row: Row) {
  return Object.fromEntries(r.keys.map((key) => [key, String(row[key] ?? "")]));
}
export function compact(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "object") {
    const v = value as Row;
    const title =
      v.display_name ?? v.name ?? v.text ?? v.content ?? v.bio ?? v.mode;
    return title
      ? String(title)
      : Array.isArray(value)
        ? `${value.length} 项`
        : `${Object.keys(v).length} 个字段`;
  }
  return String(value);
}
export function editableValues(r: Resource, row: Row): Row {
  return Object.fromEntries((r.edit ?? []).map((key) => [key, row[key]]));
}
