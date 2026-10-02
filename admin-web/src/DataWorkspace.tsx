import { useEffect, useRef, useState } from "react";
import { Dialog, DialogPanel, DialogTitle } from "@headlessui/react";
import { Check, ChevronRight, Plus, X } from "lucide-react";
import {
  api,
  editableValues,
  keysOf,
  resourcePath,
  type AdminUser,
  type Page,
  type Resource,
  type Row,
} from "./api";
import {
  Facts,
  Heading,
  labels,
  object,
  Pager,
  RawData,
  scalar,
  SearchBox,
  State,
  StructuredData,
  Tabs,
  text,
  useData,
  useSearch,
} from "./ConsoleUI";
import { RecordAvatar, RecordGallery, recordIdentity } from "./RecordImages";
import type { Ask } from "./Management";
export type Scope = { user_id?: string; character_id?: string };
export type WorkspaceProps = {
  resource: Resource;
  scope?: Scope;
  user: AdminUser;
  refresh: number;
  ask: Ask;
  changed: () => void;
  navigate?: (s: string) => void;
  embedded?: boolean;
};
const actionNames: Record<string, string> = {
  remove: "删除此关联",
  reset: "重置对话与记忆",
  archive: "下架角色",
  restore: "恢复原始状态",
  revoke_sessions: "退出所有设备",
  reset_password: "重置密码",
  disable_release: "停止资源下载",
  enable_release: "启用资源下载",
  clear_unused: "清理未使用预缓存",
  approve: "审核并启用音色",
};
const defaults: Record<string, Row> = {
  users: { username: "", password: "", display_name: "" },
  admin_users: { username: "", password: "", role: "viewer" },
  characters: {
    id: "",
    author_id: "starry-studio",
    name: "",
    description: "",
    visibility: "private",
    data: { schema_version: 1, asset_delivery: "bundled", local_preview: true },
  },
  authors: { id: "", data: { name: "", bio: "", avatar: "moon" } },
  subscriptions: { user_id: "", character_id: "" },
  follows: { user_id: "", author_id: "" },
  character_releases: {
    manifest: {
      schema_version: 1,
      character_id: "",
      release_id: "",
      version: 1,
      platform: "ios",
      runtime_version: "",
      files: [],
    },
    confirmed_distribution_rights: false,
  },
};
export function canEditResource(r: Resource, user: AdminUser) {
  return (
    user.role !== "viewer" &&
    (!r.ai || user.role === "owner") &&
    (!["admin_users", "character_releases"].includes(r.id) ||
      user.role === "owner")
  );
}
function columns(r: Resource) {
  const preferred: Record<string, string[]> = {
    users: ["profile", "starry_id", "username", "guest"],
    characters: ["name", "id", "visibility", "version"],
    authors: ["data", "id", "user_id"],
    profiles: ["name", "id", "version"],
    messages: r.ai
      ? ["role", "content", "created"]
      : ["role", "text", "created_at"],
    memories: ["content", "importance", "created"],
    admin_audit: ["actor_name", "action", "resource", "outcome", "occurred_at"],
    usage: ["kind", "status", "units", "created"],
    conversation_goals: ["character_id", "config", "progress", "version"],
  };
  return (
    preferred[r.id] ||
    r.fields
      .filter(
        (k) =>
          ![
            "data",
            "manifest",
            "config",
            "progress",
            "result",
            "metrics",
            "capabilities",
          ].includes(k),
      )
      .slice(0, 5)
  );
}
export function DataWorkspace({
  resource: r,
  scope,
  user,
  refresh,
  ask,
  changed,
  navigate,
  embedded = false,
}: WorkspaceProps) {
  const [q, setQ] = useState(""),
    query = useSearch(q),
    [cursors, setCursors] = useState([""]),
    [selected, setSelected] = useState<Row | null>(null),
    [creating, setCreating] = useState(false);
  useEffect(() => setCursors([""]), [query, r.id]);
  const filter = new URLSearchParams({
    q: query,
    after: cursors.at(-1) || "",
    ...(r.ai
      ? {
          ...(scope?.user_id ? { owner: scope.user_id } : {}),
          ...(scope?.character_id ? { character: scope.character_id } : {}),
        }
      : scope),
  });
  const path =
    (scope && !r.ai ? "/directory/records/" + r.id : resourcePath(r)) +
    "?" +
    filter;
  const { data: page, loading, error } = useData<Page>(path, refresh);
  useEffect(() => {
    if (page && selected) {
      const next = page.items.find(
        (row) =>
          JSON.stringify(keysOf(r, row)) ===
          JSON.stringify(keysOf(r, selected)),
      );
      if (next) setSelected(next);
    }
  }, [page]);
  const keys = columns(r),
    createAllowed =
      !scope && user.role === "owner" && !r.ai && r.id in defaults;
  return (
    <section className={"resource-workspace " + (embedded ? "embedded" : "")}>
      {!embedded && (
        <Heading
          title={r.name}
          description={r.description}
          action={
            createAllowed ? (
              <button className="primary" onClick={() => setCreating(true)}>
                <Plus size={15} />
                新建
              </button>
            ) : undefined
          }
        />
      )}
      <div className="panel">
        <div className="table-toolbar">
          <SearchBox
            label="搜索当前分类"
            placeholder={"搜索" + r.name}
            value={q}
            onChange={setQ}
          />
          <span className="muted">{r.ai ? "AI 运行记录" : "账户归档数据"}</span>
        </div>
        <State loading={loading} error={error} />
        {!loading && !error && (
          <>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    {keys.map((k) => (
                      <th key={k}>{labels[k] || k}</th>
                    ))}
                    <th>
                      <span className="sr-only">详情</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {page?.items.map((row, i) => {
                    const identity = recordIdentity(r, row);
                    return (
                      <tr
                        key={JSON.stringify(keysOf(r, row)) || i}
                        tabIndex={0}
                        onClick={() => setSelected(row)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") setSelected(row);
                        }}
                      >
                        {keys.map((k, j) => (
                          <td key={k}>
                            {j === 0 && identity ? (
                              <div className="identity-cell">
                                <RecordAvatar
                                  identity={identity}
                                  revision={row.version}
                                />
                                <div>
                                  <strong>{identity.name}</strong>
                                  <small>{identity.id}</small>
                                </div>
                              </div>
                            ) : (
                              <span
                                className={
                                  "cell-value " +
                                  ([
                                    "id",
                                    "user_id",
                                    "character_id",
                                    "owner",
                                  ].includes(k)
                                    ? "mono"
                                    : "")
                                }
                                title={
                                  typeof row[k] === "object"
                                    ? undefined
                                    : scalar(row[k], k)
                                }
                              >
                                {scalar(row[k], k)}
                              </span>
                            )}
                          </td>
                        ))}
                        <td>
                          <ChevronRight size={14} />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <State empty={!page?.items.length} />
          </>
        )}
        <Pager
          page={page}
          cursors={cursors}
          setCursors={setCursors}
          loading={loading}
        />
      </div>
      {selected && (
        <RecordDrawer
          key={JSON.stringify(selected)}
          resource={r}
          row={selected}
          user={user}
          ask={ask}
          changed={changed}
          refresh={refresh}
          navigate={navigate}
          close={() => setSelected(null)}
        />
      )}
      <Dialog
        open={creating}
        onClose={() => setCreating(false)}
        className="dialog-root"
      >
        <div className="dialog-shade" />
        <div className="dialog-position">
          <DialogPanel className="modal-panel">
            <div className="modal-head">
              <DialogTitle>新建{r.name}</DialogTitle>
              <button
                className="icon-button"
                aria-label="关闭"
                onClick={() => setCreating(false)}
              >
                <X size={18} />
              </button>
            </div>
            <CreateRecord
              resource={r}
              changed={changed}
              close={() => setCreating(false)}
            />
          </DialogPanel>
        </div>
      </Dialog>
    </section>
  );
}
export function RecordDrawer({
  resource: r,
  row,
  user,
  ask,
  changed,
  refresh = 0,
  navigate,
  close,
}: {
  resource: Resource;
  row: Row;
  user: AdminUser;
  ask: Ask;
  changed: () => void;
  refresh?: number;
  navigate?: (s: string) => void;
  close: () => void;
}) {
  const [tab, setTab] = useState("view"),
    [values, setValues] = useState<Row>(editableValues(r, row)),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const resetID = useRef(crypto.randomUUID()),
    edit = canEditResource(r, user),
    name =
      text(
        row.name ||
          object(row.profile).display_name ||
          object(row.data).name ||
          row.starry_id ||
          row.id,
      ) || "记录详情";
  async function mutate(action: string, password = "") {
    await api(resourcePath(r) + "/mutate", {
      method: "POST",
      body: JSON.stringify({
        keys: keysOf(r, row),
        action,
        confirmed: action !== "edit",
        reset_id: resetID.current,
        expected_version: row.version ?? 0,
        values:
          action === "edit"
            ? values
            : action === "reset_password"
              ? { password }
              : {},
      }),
    });
  }
  async function save() {
    setBusy(true);
    setError("");
    try {
      await mutate("edit");
      changed();
      setTab("view");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const identity = recordIdentity(r, row);
  return (
    <Dialog
      open
      onClose={() => {
        if (!busy) close();
      }}
      className="drawer-root"
    >
      <div className="dialog-shade" />
      <div className="drawer-position">
        <DialogPanel className="drawer-panel detail-panel">
          <header className="drawer-head">
            <div>
              {identity && (
                <RecordAvatar
                  identity={identity}
                  revision={`${row.version}:${refresh}`}
                />
              )}
              <div>
                <DialogTitle>{name}</DialogTitle>
                <span className="muted">{r.name}</span>
              </div>
            </div>
            <button
              className="icon-button"
              aria-label="关闭详情"
              onClick={close}
            >
              <X size={18} />
            </button>
          </header>
          <Tabs
            items={[
              ["view", "详情"],
              ...(edit && r.edit?.length
                ? [["edit", "编辑"] as [string, string]]
                : []),
              ["raw", "原始数据"],
            ]}
            selected={tab}
            onChange={setTab}
          />
          <div className="drawer-body">
            <State error={error} />
            {tab === "view" && (
              <>
                <RecordGallery
                  resource={r}
                  row={row}
                  revision={`${row.version}:${refresh}`}
                />
                <Facts data={row} />
                {navigate && identity && identity.kind !== "author" && (
                  <button
                    className="secondary"
                    onClick={() => {
                      close();
                      navigate(
                        (identity.kind === "user" ? "user:" : "character:") +
                          identity.id,
                      );
                    }}
                  >
                    打开{identity.kind === "user" ? "用户" : "角色"}页面
                    <ChevronRight size={14} />
                  </button>
                )}
                {edit && !!r.actions?.length && (
                  <section className="record-actions">
                    <h3>管理操作</h3>
                    {r.actions.map((action) => (
                      <button
                        key={action}
                        className={
                          [
                            "reset",
                            "remove",
                            "archive",
                            "disable_release",
                          ].includes(action)
                            ? "danger-button"
                            : "secondary"
                        }
                        onClick={() =>
                          ask({
                            title: actionNames[action] || action,
                            password: action === "reset_password",
                            danger: [
                              "reset",
                              "remove",
                              "archive",
                              "disable_release",
                            ].includes(action),
                            description:
                              action === "reset"
                                ? "将清空此用户与角色的全部对话、记忆和关系进度，无法撤销。"
                                : action === "clear_unused"
                                  ? "清理未使用的预生成回复，保留已发送消息的重播音频。"
                                  : action === "enable_release"
                                    ? "请确认已获得相关资源的再分发权。启用后用户可获取下载凭证。"
                                    : `确认对「${name}」执行此操作？操作会留存审计记录。`,
                            run: (password) => mutate(action, password),
                          })
                        }
                      >
                        {actionNames[action] || action}
                      </button>
                    ))}
                  </section>
                )}
                {r.ai && r.id === "profiles" && edit && (
                  <button
                    className="secondary"
                    onClick={() =>
                      ask({
                        title: "生成候选音色",
                        description:
                          "会调用百炼付费音色模型。候选音色须在音色任务中审核后启用。",
                        run: async () => {
                          await api(
                            "/ai/console/voices/" +
                              encodeURIComponent(String(row.id)) +
                              "/generate",
                            {
                              method: "POST",
                              body: JSON.stringify({
                                confirmed_paid: true,
                                revision: "admin-" + Date.now(),
                              }),
                            },
                          );
                        },
                      })
                    }
                  >
                    生成候选音色
                  </button>
                )}
              </>
            )}
            {tab === "edit" && (
              <form
                className="edit-form"
                onSubmit={(e) => {
                  e.preventDefault();
                  void save();
                }}
              >
                <p className="muted">
                  只编辑允许修改的字段；保存时检查记录版本。
                </p>
                <Fields
                  values={values}
                  original={editableValues(r, row)}
                  onChange={setValues}
                  expandObjects
                />
                {r.id === "users" && (
                  <label>
                    更换头像（JPEG / PNG，最多 512 KB）
                    <input
                      type="file"
                      accept="image/jpeg,image/png"
                      disabled={busy}
                      onChange={async (e) => {
                        const f = e.target.files?.[0];
                        if (!f) return;
                        if (f.size > 512 * 1024) {
                          setError("头像文件不能超过 512 KB");
                          return;
                        }
                        setBusy(true);
                        try {
                          await api(
                            "/users/" +
                              row.id +
                              "/avatar?expected_version=" +
                              row.version,
                            {
                              method: "POST",
                              body: f,
                              headers: { "Content-Type": f.type },
                            },
                          );
                          changed();
                          close();
                        } catch (err) {
                          setError((err as Error).message);
                        } finally {
                          setBusy(false);
                        }
                      }}
                    />
                  </label>
                )}
                <button
                  className="primary"
                  disabled={busy || Object.values(values).includes(undefined)}
                >
                  <Check size={15} />
                  {busy ? "保存中…" : "保存修改"}
                </button>
              </form>
            )}
            {tab === "raw" && (
              <>
                <p className="muted">完整记录；密钥与受限字段由服务器隐藏。</p>
                <pre className="raw-json">{JSON.stringify(row, null, 2)}</pre>
              </>
            )}
          </div>
        </DialogPanel>
      </div>
    </Dialog>
  );
}
function JSONInput({
  value,
  name,
  onChange,
}: {
  value: unknown;
  name: string;
  onChange: (v: unknown) => void;
}) {
  const [draft, setDraft] = useState(JSON.stringify(value ?? {}, null, 2)),
    [invalid, setInvalid] = useState(false);
  return (
    <label className="json-field">
      {labels[name] || name}
      <textarea
        className="mono"
        rows={Math.min(10, Math.max(4, draft.split("\n").length))}
        spellCheck={false}
        value={draft}
        onChange={(e) => {
          setDraft(e.target.value);
          try {
            const v = JSON.parse(e.target.value);
            if (
              !v ||
              typeof v !== "object" ||
              Array.isArray(v) !== Array.isArray(value)
            )
              throw Error();
            setInvalid(false);
            onChange(v);
          } catch {
            setInvalid(true);
            onChange(undefined);
          }
        }}
      />
      {invalid && (
        <small className="field-error">
          请输入有效的 JSON {Array.isArray(value) ? "数组" : "对象"}
        </small>
      )}
    </label>
  );
}
export function Fields({
  values,
  original,
  onChange,
  expandObjects = false,
  locked = false,
}: {
  values: Row;
  original: Row;
  onChange: (r: Row) => void;
  expandObjects?: boolean;
  locked?: boolean;
}) {
  const update = (k: string, v: unknown) => onChange({ ...values, [k]: v });
  return (
    <>
      {Object.entries(original).map(([key, source]) => {
        const v = values[key];
        if (
          locked &&
          [
            "age",
            "age_policy",
            "age_boundary",
            "adult",
            "romance_allowed",
            "visual_age",
          ].includes(key)
        )
          return (
            <div key={key} className="readonly-field">
              <span>{labels[key] || key}</span>
              <span>{scalar(source)} · 固定元数据</span>
            </div>
          );
        if (
          expandObjects &&
          source !== null &&
          typeof source === "object" &&
          !Array.isArray(source)
        )
          return (
            <fieldset key={key}>
              <legend>{labels[key] || key}</legend>
              <ObjectFields
                value={object(v)}
                original={object(source)}
                onChange={(next) => update(key, next)}
              />
            </fieldset>
          );
        if (source !== null && typeof source === "object")
          return (
            <JSONInput
              key={key}
              name={key}
              value={source}
              onChange={(next) => update(key, next)}
            />
          );
        if (typeof source === "boolean")
          return (
            <label key={key} className="toggle-field">
              {labels[key] || key}
              <input
                type="checkbox"
                checked={!!v}
                onChange={(e) => update(key, e.target.checked)}
              />
            </label>
          );
        if (key === "role" || key === "visibility")
          return (
            <label key={key}>
              {labels[key]}
              <select
                value={String(v ?? "")}
                onChange={(e) => update(key, e.target.value)}
              >
                {(key === "role"
                  ? ["viewer", "editor", "owner"]
                  : ["private", "public"]
                ).map((s) => (
                  <option key={s} value={s}>
                    {scalar(s, key)}
                  </option>
                ))}
              </select>
            </label>
          );
        return (
          <label key={key}>
            {labels[key] || key}
            {["content", "text", "description", "bio"].includes(key) ||
            String(source ?? "").length > 100 ? (
              <textarea
                rows={String(source).length > 300 ? 6 : 3}
                value={String(v ?? "")}
                onChange={(e) => update(key, e.target.value)}
              />
            ) : (
              <input
                autoComplete={key === "password" ? "new-password" : "off"}
                type={
                  key === "password"
                    ? "password"
                    : typeof source === "number"
                      ? "number"
                      : "text"
                }
                value={String(v ?? "")}
                onChange={(e) =>
                  update(
                    key,
                    typeof source === "number"
                      ? Number(e.target.value)
                      : e.target.value,
                  )
                }
              />
            )}
          </label>
        );
      })}
    </>
  );
}
function ObjectFields({
  value,
  original,
  onChange,
}: {
  value: Row;
  original: Row;
  onChange: (v: Row | undefined) => void;
}) {
  const [draft, setDraft] = useState(value);
  return (
    <Fields
      values={draft}
      original={original}
      locked
      onChange={(next) => {
        setDraft(next);
        onChange(Object.values(next).includes(undefined) ? undefined : next);
      }}
    />
  );
}
function CreateRecord({
  resource: r,
  changed,
  close,
}: {
  resource: Resource;
  changed: () => void;
  close: () => void;
}) {
  const [values, setValues] = useState<Row>(defaults[r.id]),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  return (
    <form
      className="edit-form"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setError("");
        try {
          await api("/create/" + r.id, {
            method: "POST",
            body: JSON.stringify(values),
          });
          changed();
          close();
        } catch (err) {
          setError((err as Error).message);
        } finally {
          setBusy(false);
        }
      }}
    >
      <Fields values={values} original={defaults[r.id]} onChange={setValues} />
      <State error={error} />
      <button
        className="primary"
        disabled={busy || Object.values(values).includes(undefined)}
      >
        {busy ? "创建中…" : "创建记录"}
      </button>
    </form>
  );
}
