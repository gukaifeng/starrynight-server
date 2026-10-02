import { lazy, Suspense, useEffect, useState } from "react";
import { api, compact, type Row } from "./api";
import { Ask, bytes, Json, Message, Table, useData } from "./Management";
const ModelPreview = lazy(() => import("./ModelPreview"));
type Listing = {
  items: Row[];
  next?: string;
  configured?: boolean;
  detail?: Row;
  message?: string;
};
const esc = encodeURIComponent;
function JSONPreview({ url }: { url: string }) {
  const [content, setContent] = useState<unknown>(null),
    [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    setContent(null);
    setError("");
    const load = async () => {
      const response = await fetch(url, {
        credentials: "same-origin",
        signal: controller.signal,
      });
      if (!response.ok) throw new Error("资源内容暂不可用，请刷新后重试");
      if (Number(response.headers.get("content-length")) > 1048576)
        throw new Error("JSON 超过 1 MB，请下载检查完整内容");
      const reader = response.body?.getReader();
      if (!reader) return;
      const chunks: Uint8Array[] = [];
      let length = 0;
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        length += value.length;
        if (length > 1048576) {
          await reader.cancel();
          throw new Error("JSON 超过 1 MB，请下载检查完整内容");
        }
        chunks.push(value);
      }
      const bytes = new Uint8Array(length);
      let offset = 0;
      for (const chunk of chunks) {
        bytes.set(chunk, offset);
        offset += chunk.length;
      }
      const clean = (value: unknown): unknown =>
        Array.isArray(value)
          ? value.map(clean)
          : value && typeof value === "object"
            ? Object.fromEntries(
                Object.entries(value).map(([k, v]) => [
                  k,
                  /password|token|api[_-]?key|secret|voice[_-]?id|authorization|access[_-]?key|credentials/i.test(
                    k,
                  )
                    ? "[已隐藏]"
                    : clean(v),
                ]),
              )
            : value;
      if (!controller.signal.aborted)
        setContent(clean(JSON.parse(new TextDecoder().decode(bytes))));
    };
    load().catch((e) => {
      if (!controller.signal.aborted) setError((e as Error).message);
    });
    return () => controller.abort();
  }, [url]);
  return (
    <>
      <Message text={error} />
      {content === null && !error ? (
        <p className="panel-note">正在读取资源内容…</p>
      ) : (
        <Json data={content} />
      )}
    </>
  );
}
function Preview({ name, url }: { name: string; url: string }) {
  const ext = name.toLowerCase().split(".").pop();
  if (ext === "json") return <JSONPreview url={url} />;
  if (["glb", "vrm", "fbx"].includes(ext ?? ""))
    return (
      <Suspense fallback={<p>正在准备预览…</p>}>
        <ModelPreview name={name} url={url} />
      </Suspense>
    );
  if (["png", "jpg", "jpeg", "gif", "webp"].includes(ext ?? ""))
    return <img className="resource-image" src={url} alt={name} />;
  if (["pcm", "wav", "mp3", "m4a", "ogg"].includes(ext ?? ""))
    return (
      <div className="sound-preview">
        <span className="sound-orbit" />
        <audio controls preload="none" src={url} />
        <p>播放已有文件，不调用语音生成服务。</p>
      </div>
    );
  return (
    <p className="panel-note">
      此格式支持下载检查。Unity 运行包不能直接在浏览器执行；可上传配套 GLB／FBX
      文件检查模型和动画。
    </p>
  );
}
export function MediaLibrary({
  mode,
  refresh,
  ask,
  changed,
}: {
  mode: string;
  refresh: number;
  ask: Ask;
  changed: () => void;
}) {
  const [source, setSource] = useState(mode === "audio" ? "audio" : "library"),
    [q, setQ] = useState(""),
    [after, setAfter] = useState(""),
    [history, setHistory] = useState<string[]>([]),
    [selected, setSelected] = useState<Row | null>(null),
    [uploading, setUploading] = useState(false),
    [error, setError] = useState(""),
    [character, setCharacter] = useState(""),
    [objectKey, setObjectKey] = useState(""),
    [description, setDescription] = useState("");
  const isWorker = ["audio", "voices", "models", "trash"].includes(source);
  const path = isWorker
    ? "/files/ai?group=" + source + "&q=" + esc(q) + "&after=" + esc(after)
    : source === "oss"
      ? "/objects?prefix=" +
        esc(q) +
        "&after=" +
        esc(after) +
        (selected ? "&key=" + esc(String(selected.key)) : "")
      : "/runtime/library?folder=" +
        (source === "library-trash" ? "trash" : "") +
        "&q=" +
        esc(q) +
        "&after=" +
        esc(after);
  const { data, error: loadError, loading } = useData<Listing>(path, refresh);
  const choices =
    mode === "audio"
      ? [
          ["audio", "对话语音"],
          ["voices", "音色试听"],
          ["trash", "回收站"],
        ]
      : [
          ["library", "服务器资源"],
          ["library-trash", "资源回收"],
          ["oss", "OSS 对象"],
          ["models", "推理模型"],
        ];
  const pick = (row: Row) => {
    setSelected(row);
    setDescription(String(row.description ?? ""));
    setCharacter(String(row.character_id ?? ""));
  };
  const download = selected
    ? isWorker
      ? "/admin-api/v1/files/ai/download?id=" + esc(String(selected.id))
      : source === "oss"
        ? "/admin-api/v1/objects/download?key=" + esc(String(selected.key))
        : "/admin-api/v1/runtime-download?kind=library&folder=" +
          (source === "library-trash" ? "trash" : "") +
          "&id=" +
          esc(String(selected.id))
    : "";
  const preview = download + (download ? "&preview=true" : "");
  const sendFile = async (file: File) => {
    setUploading(true);
    setError("");
    try {
      if (source === "oss" && !objectKey.trim())
        throw new Error("请填写新的 OSS 对象路径");
      await api(
        source === "oss"
          ? "/objects/upload?key=" + esc(objectKey)
          : "/library/upload?name=" +
              esc(file.name) +
              "&character_id=" +
              esc(character),
        {
          method: "POST",
          body: file,
          headers: { "Content-Type": "application/octet-stream" },
        },
      );
      changed();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setUploading(false);
    }
  };
  return (
    <>
      <div className="management-tabs">
        {choices.map(([id, name]) => (
          <button
            key={id}
            className={source === id ? "active" : ""}
            onClick={() => {
              setSource(id);
              setAfter("");
              setHistory([]);
              setSelected(null);
              setQ("");
            }}
          >
            {name}
          </button>
        ))}
      </div>
      <Message text={error || loadError} />
      <div className="management-toolbar">
        <input
          aria-label="搜索文件"
          placeholder={
            source === "oss" ? "按对象路径前缀搜索" : "搜索文件名称或资源说明"
          }
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setAfter("");
            setSelected(null);
          }}
        />
        {!isWorker && source !== "library-trash" && (
          <label className="secondary upload-control">
            {uploading ? "上传并校验中…" : "上传文件"}
            <input
              aria-label="上传资源文件"
              type="file"
              disabled={
                uploading || (source === "oss" && data?.configured === false)
              }
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) void sendFile(file);
                e.target.value = "";
              }}
            />
          </label>
        )}
      </div>
      {!isWorker && source !== "library-trash" && (
        <div className="upload-options">
          <label>
            关联角色 ID
            <input
              value={character}
              onChange={(e) => setCharacter(e.target.value)}
              placeholder="可选，填写目录中的角色 ID"
            />
          </label>
          {source === "oss" && (
            <label>
              新对象路径
              <input
                value={objectKey}
                onChange={(e) => setObjectKey(e.target.value)}
                placeholder="characters/角色/版本/model.glb"
              />
            </label>
          )}
          <p className="panel-note">
            单文件最多 512
            MB。上传保持私有，不自动发布；新版本使用新路径，保留原发布文件。
          </p>
        </div>
      )}
      {data?.configured === false && (
        <div className="panel storage-empty">
          <h2>OSS 尚未配置</h2>
          <p>{data.message}</p>
          <p>
            服务器资源库现在即可使用。配置 OSS
            后，可浏览、上传、预览并管理对象。
          </p>
        </div>
      )}
      <div className={"management-split " + (selected ? "has-detail" : "")}>
        <section className="panel management-list">
          {loading && <p className="panel-note">正在读取文件…</p>}
          <Table
            rows={data?.items ?? []}
            selected={selected}
            onSelect={pick}
            columns={
              source === "oss"
                ? [
                    ["key", "对象路径"],
                    ["bytes", "大小"],
                    ["storage_class", "存储类型"],
                  ]
                : [
                    ["name", "文件"],
                    ["character_id", "关联角色"],
                    ["bytes", "大小"],
                    ["modified", "更新"],
                  ]
            }
          />
          <div className="pagination">
            <button
              className="secondary"
              disabled={!history.length}
              onClick={() => {
                setAfter(history.at(-1) ?? "");
                setHistory(history.slice(0, -1));
                setSelected(null);
              }}
            >
              上一页
            </button>
            <button
              className="secondary"
              disabled={!data?.next}
              onClick={() => {
                setHistory([...history, after]);
                setAfter(data?.next ?? "");
                setSelected(null);
              }}
            >
              下一页
            </button>
          </div>
        </section>
        {selected && (
          <aside className="panel management-detail">
            <div className="section-title">
              <h2>{String(selected.name ?? selected.key)}</h2>
              <button
                aria-label="关闭文件详情"
                className="icon-button"
                onClick={() => setSelected(null)}
              >
                ×
              </button>
            </div>
            <p className="file-size">{bytes(selected.bytes)}</p>
            <Preview
              name={String(selected.name ?? selected.key)}
              url={preview}
            />
            {source === "library" && (
              <>
                <label>
                  关联角色 ID
                  <input
                    value={character}
                    onChange={(e) => setCharacter(e.target.value)}
                  />
                </label>
                <label>
                  资源说明
                  <textarea
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                  />
                </label>
                <button
                  className="secondary"
                  onClick={() =>
                    ask({
                      title: "保存资源信息",
                      description: "只更新管理信息，文件内容保持不变。",
                      run: async () => {
                        await api("/runtime/library", {
                          method: "POST",
                          body: JSON.stringify({
                            confirmed: true,
                            id: selected.id,
                            operation: "metadata",
                            expected_version: selected.version ?? 1,
                            character_id: character,
                            description,
                          }),
                        });
                        changed();
                      },
                    })
                  }
                >
                  保存信息
                </button>
              </>
            )}
            {isWorker && !!selected.reference && (
              <>
                <h3>关联对话或角色</h3>
                <Json data={selected.reference} />
              </>
            )}
            <details>
              <summary>文件与校验信息</summary>
              <Json
                data={source === "oss" ? (data?.detail ?? selected) : selected}
              />
            </details>
            <div className="detail-actions">
              <a
                className="secondary"
                href={download + (isWorker ? "&raw=true" : "")}
                download
              >
                下载原始文件
              </a>
              {(source === "library" ||
                source === "library-trash" ||
                source === "oss" ||
                !!selected.deletable) && (
                <button
                  className="danger-button"
                  onClick={() =>
                    ask({
                      title:
                        source === "trash" || source === "library-trash"
                          ? "恢复文件"
                          : "移除此文件",
                      danger: source !== "trash" && source !== "library-trash",
                      description:
                        source === "oss"
                          ? "仅允许移除没有被任何发布版本引用的对象。"
                          : source === "audio"
                            ? "将移入回收站。历史对话的这段声音可能无法直接重播，文字不受影响。"
                            : source === "trash" || source === "library-trash"
                              ? "恢复到原来的声音目录，不调用生成接口。"
                              : "文件移入回收站，正在使用的音色试听不能移除。",
                      run: async () => {
                        if (isWorker)
                          await api("/files/ai/delete", {
                            method: "POST",
                            body: JSON.stringify({
                              id: selected.id,
                              version: selected.version,
                              confirmed: true,
                              action:
                                source === "trash" || source === "library-trash"
                                  ? "restore"
                                  : "delete",
                            }),
                          });
                        else if (source === "oss")
                          await api("/objects/delete", {
                            method: "POST",
                            body: JSON.stringify({
                              key: selected.key,
                              etag: selected.etag,
                              confirmed: true,
                            }),
                          });
                        else
                          await api("/runtime/library", {
                            method: "POST",
                            body: JSON.stringify({
                              id: selected.id,
                              operation:
                                source === "library-trash"
                                  ? "restore"
                                  : "delete",
                              confirmed: true,
                            }),
                          });
                        setSelected(null);
                        changed();
                      },
                    })
                  }
                >
                  {source === "trash" || source === "library-trash"
                    ? "恢复文件"
                    : "移除文件"}
                </button>
              )}
            </div>
          </aside>
        )}
      </div>
    </>
  );
}
