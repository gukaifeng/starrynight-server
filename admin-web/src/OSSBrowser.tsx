import { useState } from "react";
import {
  ArrowLeft,
  ChevronRight,
  Download,
  File,
  Folder,
  Search,
  X,
} from "lucide-react";
import { Heading, object, Panel, State, text, useData } from "./ConsoleUI";
import { bytes, time } from "./Management";
import { ResourcePreview } from "./MediaLibrary";
import type { Row } from "./api";

type OSSObject = {
  key: string;
  bytes: number;
  modified: string;
  storage_class: string;
  etag: string;
};
type OSSListing = {
  configured: boolean;
  bucket?: string;
  prefix?: string;
  directories?: string[];
  items: OSSObject[];
  next?: string;
  detail?: Row;
  detail_error?: string;
  message?: string;
};
export function OSSBrowser({ refresh }: { refresh: number }) {
  const [prefix, setPrefix] = useState(""),
    [draft, setDraft] = useState(""),
    [folders, setFolders] = useState(true);
  const [after, setAfter] = useState(""),
    [history, setHistory] = useState<string[]>([]),
    [selected, setSelected] = useState<OSSObject | null>(null),
    [preview, setPreview] = useState(false);
  const query = new URLSearchParams({
    prefix,
    after,
    folders: String(folders),
  });
  if (selected) query.set("key", selected.key);
  const { data, error, loading } = useData<OSSListing>(
    "/objects?" + query,
    refresh,
  );
  const browse = (value: string) => {
    setPrefix(value);
    setDraft(value);
    setAfter("");
    setHistory([]);
    setSelected(null);
    setPreview(false);
  };
  const changeMode = (value: boolean) => {
    setFolders(value);
    setAfter("");
    setHistory([]);
    setSelected(null);
    setPreview(false);
  };
  const directories = data?.directories ?? [],
    items = data?.items ?? [];
  const crumbs = prefix.split("/").filter(Boolean);
  const detail = data?.detail;
  const download = selected
    ? "/admin-api/v1/objects/download?key=" + encodeURIComponent(selected.key)
    : "";
  const pick = (item: OSSObject) => {
    setSelected(item);
    setPreview(false);
  };
  return (
    <div className="oss-browser">
      <Heading
        title="OSS Bucket"
        description="浏览项目 Bucket 中的目录、文件与资源引用。"
      />
      <Panel className="oss-browser-controls">
        <div className="oss-bucket-head">
          <div>
            <span className="muted">当前 Bucket</span>
            <strong>
              {data?.bucket ||
                (data?.configured === false ? "尚未配置" : "正在读取…")}
            </strong>
          </div>
          <div className="segmented" role="group" aria-label="OSS 浏览方式">
            <button
              aria-pressed={folders}
              className={folders ? "active" : ""}
              onClick={() => changeMode(true)}
            >
              目录视图
            </button>
            <button
              aria-pressed={!folders}
              className={!folders ? "active" : ""}
              onClick={() => changeMode(false)}
            >
              全部对象
            </button>
          </div>
        </div>
        <form
          className="oss-prefix-search"
          onSubmit={(e) => {
            e.preventDefault();
            browse(draft.trim());
          }}
        >
          <Search size={16} />
          <input
            aria-label="OSS 路径前缀"
            placeholder="输入目录或文件路径前缀，如 characters/"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            maxLength={1024}
          />
          <button className="secondary" type="submit">
            查找
          </button>
          {prefix && (
            <button
              type="button"
              className="quiet-button"
              onClick={() => browse("")}
            >
              回到根目录
            </button>
          )}
        </form>
        <nav className="oss-breadcrumbs" aria-label="Bucket 路径">
          <button onClick={() => browse("")}>
            <Folder size={14} />
            Bucket 根目录
          </button>
          {crumbs.map((part, i) => (
            <span key={i}>
              <ChevronRight size={13} />
              <button
                onClick={() =>
                  browse(
                    crumbs.slice(0, i + 1).join("/") +
                      (i < crumbs.length - 1 || prefix.endsWith("/")
                        ? "/"
                        : ""),
                  )
                }
              >
                {part}
              </button>
            </span>
          ))}
        </nav>
      </Panel>
      <State loading={loading} error={error} />
      {data?.configured === false && (
        <Panel>
          <p className="panel-note">
            {data.message || "此服务器尚未配置 OSS 存储。"}
          </p>
        </Panel>
      )}
      {data?.configured && (
        <div className={"oss-workspace " + (selected ? "with-detail" : "")}>
          <Panel
            title={folders ? "当前目录" : "匹配的全部对象"}
            className="oss-file-list"
            action={
              prefix ? (
                <button
                  className="secondary"
                  onClick={() =>
                    browse(
                      crumbs.slice(0, -1).join("/") +
                        (crumbs.length > 1 ? "/" : ""),
                    )
                  }
                >
                  <ArrowLeft size={14} />
                  上一级目录
                </button>
              ) : undefined
            }
          >
            <p className="panel-note">
              本页 {directories.length} 个目录、{items.length} 个文件 · 文件共{" "}
              {bytes(items.reduce((n, item) => n + item.bytes, 0))}。
              {data.next ? "还有后续内容，可翻页查看。" : "已到当前范围末页。"}
            </p>
            {!directories.length && !items.length && !loading ? (
              <div className="state">
                {prefix ? "这个前缀下没有目录或文件。" : "Bucket 暂无对象。"}
              </div>
            ) : (
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>名称 / 对象路径</th>
                      <th>大小</th>
                      <th>更新时间</th>
                      <th>存储类型</th>
                    </tr>
                  </thead>
                  <tbody>
                    {directories.map((directory) => (
                      <tr key={"folder:" + directory}>
                        <td>
                          <button
                            className="oss-object-name"
                            onClick={() => browse(directory)}
                            aria-label={`打开目录 ${directory}`}
                          >
                            <Folder size={17} />
                            <span>
                              {directory.slice(prefix.length) || directory}
                            </span>
                          </button>
                        </td>
                        <td>—</td>
                        <td>—</td>
                        <td>目录</td>
                      </tr>
                    ))}
                    {items.map((item) => (
                      <tr
                        key={item.key}
                        className={selected?.key === item.key ? "selected" : ""}
                      >
                        <td>
                          <button
                            className="oss-object-name"
                            onClick={() => pick(item)}
                            aria-label={`查看文件 ${item.key}`}
                          >
                            <File size={17} />
                            <span>
                              {folders
                                ? item.key.slice(prefix.length) || item.key
                                : item.key}
                            </span>
                          </button>
                        </td>
                        <td className="mono">{bytes(item.bytes)}</td>
                        <td>{time(item.modified)}</td>
                        <td>{item.storage_class || "Standard"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <div className="pagination">
              <span>第 {history.length + 1} 页</span>
              <div>
                <button
                  className="secondary"
                  disabled={!history.length || loading}
                  onClick={() => {
                    setAfter(history.at(-1)!);
                    setHistory((old) => old.slice(0, -1));
                    setSelected(null);
                    setPreview(false);
                  }}
                >
                  上一页
                </button>
                <button
                  className="secondary"
                  disabled={!data.next || loading}
                  onClick={() => {
                    setHistory((old) => [...old, after]);
                    setAfter(data.next!);
                    setSelected(null);
                    setPreview(false);
                  }}
                >
                  下一页
                </button>
              </div>
            </div>
          </Panel>
          {selected && (
            <Panel
              title="文件详情"
              className="oss-object-detail"
              action={
                <button
                  className="icon-button"
                  aria-label="关闭文件详情"
                  onClick={() => {
                    setSelected(null);
                    setPreview(false);
                  }}
                >
                  <X size={17} />
                </button>
              }
            >
              <div className="oss-detail-body">
                <p className="oss-detail-key">{selected.key}</p>
                <dl>
                  <dt>大小</dt>
                  <dd>{bytes(detail?.bytes ?? selected.bytes)}</dd>
                  <dt>更新时间</dt>
                  <dd>{time(detail?.modified ?? selected.modified)}</dd>
                  <dt>存储类型</dt>
                  <dd>
                    {text(detail?.storage_class) || selected.storage_class}
                  </dd>
                  <dt>文件类型</dt>
                  <dd>{text(detail?.content_type) || "正在读取…"}</dd>
                  <dt>ETag</dt>
                  <dd className="mono">
                    {text(detail?.etag) || selected.etag}
                  </dd>
                </dl>
                <State error={data.detail_error} />
                <div className="oss-file-actions">
                  <a className="secondary" href={download}>
                    <Download size={14} />
                    下载文件
                  </a>
                  <button
                    className="secondary"
                    aria-pressed={preview}
                    onClick={() => setPreview((v) => !v)}
                  >
                    {preview ? "收起预览" : "预览文件"}
                  </button>
                </div>
                {preview && (
                  <ResourcePreview
                    name={selected.key}
                    url={download + "&preview=true"}
                  />
                )}
                {detail && (
                  <>
                    <h3>角色资源引用</h3>
                    {Array.isArray(detail.references) &&
                    detail.references.length ? (
                      <ul className="oss-references">
                        {detail.references.map((raw, i) => {
                          const reference = object(raw);
                          return (
                            <li key={i}>
                              <a
                                href={
                                  "#" +
                                  encodeURIComponent(
                                    "character:" + text(reference.character_id),
                                  )
                                }
                              >
                                {text(reference.character_id)}
                              </a>
                              <small>
                                {reference.kind === "marketplace"
                                  ? "发现页预览"
                                  : `${text(reference.platform)} · 版本 ${reference.version}`}{" "}
                                · {reference.enabled ? "已启用" : "未启用"}
                              </small>
                            </li>
                          );
                        })}
                      </ul>
                    ) : (
                      <p className="muted">
                        没有角色发布版本或发现预览引用此对象。
                      </p>
                    )}
                    <h3>自定义元数据</h3>
                    {Object.keys(object(detail.metadata)).length ? (
                      <dl>
                        {Object.entries(object(detail.metadata)).map(
                          ([key, value]) => (
                            <div key={key}>
                              <dt>{key}</dt>
                              <dd>{String(value)}</dd>
                            </div>
                          ),
                        )}
                      </dl>
                    ) : (
                      <p className="muted">没有自定义元数据。</p>
                    )}
                  </>
                )}
              </div>
            </Panel>
          )}
        </div>
      )}
    </div>
  );
}
