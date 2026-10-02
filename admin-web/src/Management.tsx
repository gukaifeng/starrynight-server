import { useState } from "react";
import { compact, type Row } from "./api";
import { StructuredData } from "./ConsoleUI";
import { MediaLibrary } from "./MediaLibrary";
import { SystemManagement } from "./SystemManagement";

export type Ask = (options: {
  title: string;
  description: string;
  danger?: boolean;
  password?: boolean;
  run: (value: string) => Promise<void>;
}) => void;
export const tools = [
  { id: "library", name: "资源与模型" },
  { id: "audio", name: "声音文件" },
  { id: "cache", name: "会话与缓存" },
  { id: "backups", name: "备份与恢复" },
  { id: "config", name: "运行配置" },
  { id: "releases", name: "版本与证书" },
  { id: "files", name: "服务器文件" },
  { id: "jobs", name: "维护任务" },
];
export { useData } from "./ConsoleUI";
export function bytes(value: unknown) {
  const n = Number(value ?? 0);
  return n >= 1073741824
    ? (n / 1073741824).toFixed(2) + " GB"
    : n >= 1048576
      ? (n / 1048576).toFixed(1) + " MB"
      : n >= 1024
        ? (n / 1024).toFixed(1) + " KB"
        : n + " B";
}
export function time(value: unknown) {
  if (!value) return "—";
  return new Date(
    typeof value === "number" ? value * 1000 : String(value),
  ).toLocaleString();
}
export function Table({
  rows,
  columns,
  onSelect,
  selected,
}: {
  rows: Row[];
  columns: [string, string][];
  onSelect?: (row: Row) => void;
  selected?: Row | null;
}) {
  return (
    <div className="table-scroll management-table">
      <table>
        <thead>
          <tr>
            {columns.map(([key, label]) => (
              <th key={key}>{label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr
              key={String(row.id ?? row.key ?? row.name ?? i)}
              className={selected === row ? "selected" : ""}
              tabIndex={onSelect ? 0 : undefined}
              onClick={() => onSelect?.(row)}
              onKeyDown={(e) => {
                if (e.key === "Enter") onSelect?.(row);
              }}
            >
              {columns.map(([key]) => (
                <td key={key}>
                  {key === "bytes"
                    ? bytes(row[key])
                    : key === "created" || key === "modified"
                      ? time(row[key])
                      : compact(row[key])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {!rows.length && <p className="empty">暂无记录</p>}
    </div>
  );
}
export function Message({ text }: { text: string }) {
  return text ? (
    <p className="error-note" role="alert">
      {text}
    </p>
  ) : null;
}
export function Json({ data }: { data: unknown }) {
  return (
    <div className="management-data">
      <StructuredData value={data} />
    </div>
  );
}
export function Management({
  view,
  refresh,
  ask,
}: {
  view: string;
  refresh: number;
  ask: Ask;
}) {
  const [ownRefresh, setOwnRefresh] = useState(0),
    [notice, setNotice] = useState("");
  const changed = () => {
    setOwnRefresh((n) => n + 1);
    setNotice("操作已完成，数据已刷新");
  };
  const heading = tools.find((t) => t.id === view)?.name ?? view;
  return (
    <section className="management-workspace">
      <div className="page-heading">
        <div>
          <h1>{heading}</h1>
          <p>
            {view === "audio"
              ? "试听已有语音，检查角色音色和持久化缓存。"
              : view === "library"
                ? "照看角色的模型、贴图、封面与发布资源。"
                : "管理实际服务器数据，操作结果可在维护任务与审计中查看。"}
          </p>
        </div>
        <button
          className="secondary"
          onClick={() => {
            setOwnRefresh((n) => n + 1);
            setNotice("");
          }}
        >
          刷新
        </button>
      </div>
      {notice && (
        <p className="management-notice" role="status">
          {notice}
        </p>
      )}
      {view === "library" || view === "audio" ? (
        <MediaLibrary
          mode={view}
          refresh={refresh + ownRefresh}
          ask={ask}
          changed={changed}
        />
      ) : (
        <SystemManagement
          view={view}
          refresh={refresh + ownRefresh}
          ask={ask}
          changed={changed}
        />
      )}
    </section>
  );
}
