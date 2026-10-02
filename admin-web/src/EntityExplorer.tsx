import { useEffect, useState, type ReactNode } from "react";
import { ArrowLeft, ChevronRight, Link2, Pencil, Users, X } from "lucide-react";
import { type Page, type Resource, type Row } from "./api";
import {
  Facts,
  Heading,
  labels,
  number,
  object,
  Pager,
  Panel,
  RawData,
  scalar,
  SearchBox,
  State,
  Stats,
  StructuredData,
  Tabs,
  text,
  useData,
  userName,
  useSearch,
} from "./ConsoleUI";
import { RecordAvatar, RecordGallery } from "./RecordImages";
import type { Scope } from "./DataWorkspace";
export type EntityScope = Scope;
export type ResourceRenderer = (r: Resource, scope: Scope) => ReactNode;
type Detail = {
  entity: Row;
  stats: Row;
  settings?: Row;
  author?: Row;
  owner?: Row;
};
export function scopedResources(
  resources: Resource[],
  scope: Scope,
  ai: boolean,
) {
  return resources.filter(
    (r) =>
      !!r.ai === ai &&
      (ai
        ? !["config", "prompts"].includes(r.id) &&
          (!scope.user_id ||
            r.fields.includes("owner") ||
            r.id === "reply_embeddings") &&
          (!scope.character_id ||
            r.fields.includes("character") ||
            ["profiles", "reply_embeddings"].includes(r.id))
        : (!scope.user_id ||
            r.fields.includes("user_id") ||
            ["users", "characters"].includes(r.id)) &&
          (!scope.character_id ||
            r.fields.includes("character_id") ||
            r.id === "characters")),
  );
}
export function ScopedData({
  resources,
  scope,
  ai,
  renderResource,
  initial,
}: {
  resources: Resource[];
  scope: Scope;
  ai: boolean;
  renderResource: ResourceRenderer;
  initial?: string;
}) {
  const list = scopedResources(resources, scope, ai),
    [selected, setSelected] = useState(
      initial || (ai ? "messages" : "preferences"),
    );
  const current = list.find((r) => r.id === selected) || list[0];
  return (
    <section className="scoped-data">
      <div className="scope-toolbar">
        <label>
          {ai ? "AI 数据分类" : "账户数据分类"}
          <select
            aria-label={ai ? "AI 数据分类" : "账户数据分类"}
            value={current?.id || ""}
            onChange={(e) => setSelected(e.target.value)}
          >
            {list.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </select>
        </label>
        <p>
          {ai
            ? "推理服务实际使用的上下文、记忆与预生成回复。"
            : "当前对象的同步记录与内容归档。"}
        </p>
      </div>
      {current ? (
        <>
          <h2 className="resource-title">{current.name}</h2>
          {renderResource(current, scope)}
        </>
      ) : (
        <State empty />
      )}
    </section>
  );
}
function WorkerSummary({ scope, refresh }: { scope: Scope; refresh: number }) {
  const p = new URLSearchParams({
      ...(scope.user_id ? { owner: scope.user_id } : {}),
      ...(scope.character_id ? { character: scope.character_id } : {}),
    }),
    { data, error, loading } = useData<Row>(
      "/ai/console/entity-summary?" + p,
      refresh,
    );
  return (
    <Panel title="AI 运行统计" className="worker-summary">
      <p className="panel-note">独立于聊天归档，不合并统计。</p>
      <State loading={loading} error={error} />
      {data && (
        <>
          <Stats
            items={["messages", "memories", "requests", "reaction_drafts"].map(
              (k) => [k === "messages" ? "上下文消息" : labels[k], data[k]],
            )}
          />
          <RawData value={data} />
        </>
      )}
    </Panel>
  );
}
export function EntityExplorer({
  view,
  resources,
  refresh,
  navigate,
  renderResource,
  editEntity,
}: {
  view: string;
  resources: Resource[];
  refresh: number;
  navigate: (s: string) => void;
  renderResource: ResourceRenderer;
  editEntity?: (r: Resource, row: Row) => void;
}) {
  const isUser = view === "directory:users" || view.startsWith("user:"),
    id = view.includes(":") ? view.slice(view.indexOf(":") + 1) : "";
  return view.startsWith("directory:") ? (
    <Directory
      key={view}
      kind={isUser ? "users" : "characters"}
      refresh={refresh}
      navigate={navigate}
    />
  ) : (
    <EntityDetail
      key={view}
      kind={isUser ? "users" : "characters"}
      id={id}
      resources={resources}
      refresh={refresh}
      navigate={navigate}
      renderResource={renderResource}
      editEntity={editEntity}
    />
  );
}
function Directory({
  kind,
  refresh,
  navigate,
}: {
  kind: "users" | "characters";
  refresh: number;
  navigate: (s: string) => void;
}) {
  const isUser = kind === "users",
    [q, setQ] = useState(""),
    query = useSearch(q),
    [filter, setFilter] = useState(""),
    [limit, setLimit] = useState("25"),
    [cursors, setCursors] = useState([""]);
  useEffect(() => setCursors([""]), [query, filter, limit]);
  const { data, loading, error } = useData<Page>(
    "/directory/" +
      kind +
      "?" +
      new URLSearchParams({
        q: query,
        kind: filter,
        limit,
        after: cursors.at(-1) || "",
      }),
    refresh,
  );
  return (
    <>
      <Heading
        title={isUser ? "用户" : "角色"}
        description={
          isUser
            ? "查询账户，查看资料、关系与完整对话记录。"
            : "管理角色资料，查看订阅者与对话情况。"
        }
      />
      <section className="panel">
        <div className="table-toolbar">
          <SearchBox
            label={isUser ? "搜索用户" : "搜索角色"}
            placeholder={isUser ? "昵称、星夜号、账号或 UUID" : "角色名称或 ID"}
            value={q}
            onChange={setQ}
          />
          <div className="toolbar-filters">
            {isUser && (
              <select
                aria-label="用户类型"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
              >
                <option value="">全部用户</option>
                <option value="registered">注册用户</option>
                <option value="guest">访客</option>
              </select>
            )}
            <select
              aria-label="每页数量"
              value={limit}
              onChange={(e) => setLimit(e.target.value)}
            >
              {["10", "25", "50"].map((n) => (
                <option key={n} value={n}>
                  {n} 条 / 页
                </option>
              ))}
            </select>
          </div>
        </div>
        <State loading={loading} error={error} />
        {!loading && !error && (
          <>
            <div className="table-scroll entity-directory-table">
              <table>
                <thead>
                  <tr>
                    <th>{isUser ? "用户" : "角色"}</th>
                    <th>{isUser ? "星夜号" : "角色 ID"}</th>
                    <th>{isUser ? "登录账号" : "可见性"}</th>
                    <th>{isUser ? "账户类型" : "版本"}</th>
                    <th>{isUser ? "注册时间" : "更新时间"}</th>
                    <th>
                      <span className="sr-only">详情</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {data?.items.map((row) => {
                    const name = isUser
                      ? userName(row)
                      : text(row.name) || text(row.id);
                    return (
                      <tr
                        key={text(row.id)}
                        data-entity-id={text(row.id)}
                        tabIndex={0}
                        onClick={() =>
                          navigate((isUser ? "user:" : "character:") + row.id)
                        }
                        onKeyDown={(e) => {
                          if (e.key === "Enter")
                            navigate(
                              (isUser ? "user:" : "character:") + row.id,
                            );
                        }}
                      >
                        <td>
                          <div className="identity-cell">
                            <RecordAvatar
                              identity={{
                                kind: isUser ? "user" : "character",
                                id: text(row.id),
                                name,
                              }}
                              revision={row.version}
                            />
                            <div>
                              <strong>{name}</strong>
                              {isUser && (
                                <small className="mono">{text(row.id)}</small>
                              )}
                            </div>
                          </div>
                        </td>
                        <td className="mono">
                          {scalar(isUser ? row.starry_id : row.id)}
                        </td>
                        <td>
                          {scalar(
                            isUser ? row.username : row.visibility,
                            isUser ? "username" : "visibility",
                          )}
                        </td>
                        <td>
                          {isUser ? (
                            <span
                              className={
                                "badge " + (row.guest ? "" : "positive")
                              }
                            >
                              {row.guest ? "访客" : "已注册"}
                            </span>
                          ) : (
                            number(row.version)
                          )}
                        </td>
                        <td className="muted nowrap">
                          {scalar(
                            isUser ? row.created_at : row.updated_at,
                            isUser ? "created_at" : "updated_at",
                          )}
                        </td>
                        <td>
                          <ChevronRight size={14} />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <State empty={!data?.items.length} />
          </>
        )}
        <Pager
          page={data}
          loading={loading}
          cursors={cursors}
          setCursors={setCursors}
        />
      </section>
    </>
  );
}
function EntityDetail({
  kind,
  id,
  resources,
  refresh,
  navigate,
  renderResource,
  editEntity,
}: {
  kind: "users" | "characters";
  id: string;
  resources: Resource[];
  refresh: number;
  navigate: (s: string) => void;
  renderResource: ResourceRenderer;
  editEntity?: (r: Resource, row: Row) => void;
}) {
  const isUser = kind === "users",
    { data, error, loading } = useData<Detail>(
      "/directory/" + kind + "/" + encodeURIComponent(id),
      refresh,
    ),
    [tab, setTab] = useState("profile"),
    scope: Scope = isUser ? { user_id: id } : { character_id: id };
  const r = resources.find((r) => !r.ai && r.id === kind);
  if (!data)
    return (
      <>
        <button
          className="back-link"
          onClick={() => navigate("directory:" + kind)}
        >
          <ArrowLeft size={15} />
          {isUser ? "用户列表" : "角色列表"}
        </button>
        <State loading={loading} error={error} />
      </>
    );
  const row = data.entity,
    name = isUser ? userName(row) : text(row.name),
    profile = object(row.profile);
  return (
    <div className="entity-page">
      <button
        className="back-link"
        onClick={() => navigate("directory:" + kind)}
      >
        <ArrowLeft size={15} />
        {isUser ? "用户列表" : "角色列表"}
      </button>
      <header className="entity-hero">
        <RecordAvatar
          className="entity-avatar"
          identity={{ kind: isUser ? "user" : "character", id, name }}
          revision={row.version}
        />
        <div className="entity-heading">
          <h1>{name}</h1>
          <p>
            {isUser ? text(row.starry_id) || "访客账户" : id}
            <span
              className={"badge " + (isUser && !row.guest ? "positive" : "")}
            >
              {isUser
                ? row.guest
                  ? "访客"
                  : "注册用户"
                : scalar(row.visibility, "visibility")}
            </span>
          </p>
          {!!(isUser ? profile.bio : row.description) && (
            <p className="entity-bio">
              {text(isUser ? profile.bio : row.description)}
            </p>
          )}
        </div>
        {r && editEntity && (
          <button className="secondary" onClick={() => editEntity(r, row)}>
            <Pencil size={14} />
            管理资料
          </button>
        )}
      </header>
      <Tabs
        items={[
          ["profile", "资料概览"],
          ["relations", isUser ? "角色与羁绊" : "订阅者与对话用户"],
          ["archive", isUser ? "账户全部数据" : "角色全部数据"],
          ["ai", "AI 运行数据"],
        ]}
        selected={tab}
        onChange={setTab}
      />
      <div className="tab-content" role="tabpanel">
        {tab === "profile" && (
          <div className="profile-layout">
            <div className="profile-main">
              <Panel
                title={isUser ? "账户资料" : "角色资料"}
                className="entity-info"
              >
                <Facts
                  data={row}
                  keys={
                    isUser
                      ? [
                          "id",
                          "starry_id",
                          "username",
                          "guest",
                          "created_at",
                          "version",
                        ]
                      : [
                          "id",
                          "name",
                          "description",
                          "author_id",
                          "base_id",
                          "visibility",
                          "updated_at",
                          "version",
                        ]
                  }
                />
                {isUser ? (
                  <>
                    <h3 className="subsection-title">个人资料</h3>
                    <StructuredData value={row.profile} />
                  </>
                ) : (
                  <>
                    <h3 className="subsection-title">角色信息</h3>
                    <StructuredData value={row.data} />
                  </>
                )}
                <RawData value={row} />
              </Panel>
              {isUser ? (
                <Panel title="全局设置">
                  <StructuredData value={data.settings} />
                </Panel>
              ) : (
                r && (
                  <Panel title="头像与封面">
                    <RecordGallery
                      resource={r}
                      row={row}
                      revision={row.version}
                    />
                  </Panel>
                )
              )}
              {data.author && (
                <Panel title="作者资料">
                  <div className="author-inline">
                    <RecordAvatar
                      identity={{
                        kind: "author",
                        id: text(data.author.id),
                        name: text(object(data.author.data).name) || "作者",
                      }}
                      revision={data.author.version}
                    />
                    <div>
                      <strong>
                        {text(object(data.author.data).name) ||
                          text(data.author.id)}
                      </strong>
                      <span className="muted">
                        {text(object(data.author.data).bio)}
                      </span>
                    </div>
                  </div>
                  <Facts data={data.author} />
                  {!!data.author.user_id && (
                    <button
                      className="text-button"
                      onClick={() => navigate("user:" + data.author!.user_id)}
                    >
                      查看作者账户
                      <ChevronRight size={14} />
                    </button>
                  )}
                </Panel>
              )}
              {!!data.owner && (
                <Panel title="创建用户">
                  <button
                    className="text-button"
                    onClick={() => navigate("user:" + data.owner!.id)}
                  >
                    {userName(data.owner)}
                    <ChevronRight size={14} />
                  </button>
                </Panel>
              )}
            </div>
            <aside className="profile-aside">
              <Panel title="账户归档统计">
                <Stats
                  items={
                    (isUser
                      ? [
                          ["订阅角色", data.stats.subscriptions],
                          ["关注作者", data.stats.follows],
                          ["创建角色", data.stats.created_characters],
                          ["会话", data.stats.conversations],
                        ]
                      : [
                          ["订阅用户", data.stats.subscriptions],
                          ["对话用户", data.stats.chatters],
                          ["会话", data.stats.conversations],
                        ]) as [string, unknown][]
                  }
                />
                <div className="compact-metrics">
                  {["messages", "user_messages", "ai_messages"].map((k) => (
                    <div key={k}>
                      <span>{k === "messages" ? "归档消息" : labels[k]}</span>
                      <strong>{number(data.stats[k])}</strong>
                    </div>
                  ))}
                </div>
                <p className="panel-note">仅统计账户同步的记录。</p>
              </Panel>
              <WorkerSummary scope={scope} refresh={refresh} />
            </aside>
          </div>
        )}
        {tab === "relations" && (
          <Relationships
            scope={scope}
            resources={resources}
            refresh={refresh}
            navigate={navigate}
            renderResource={renderResource}
          />
        )}
        {tab === "archive" && (
          <ScopedData
            resources={resources}
            scope={scope}
            ai={false}
            initial={isUser ? "users" : "characters"}
            renderResource={renderResource}
          />
        )}
        {tab === "ai" && (
          <>
            <WorkerSummary scope={scope} refresh={refresh} />
            <ScopedData
              resources={resources}
              scope={scope}
              ai
              initial={isUser ? "messages" : "profiles"}
              renderResource={renderResource}
            />
          </>
        )}
      </div>
    </div>
  );
}
function Relationships({
  scope,
  resources,
  refresh,
  navigate,
  renderResource,
}: {
  scope: Scope;
  resources: Resource[];
  refresh: number;
  navigate: (s: string) => void;
  renderResource: ResourceRenderer;
}) {
  const [kind, setKind] = useState(""),
    [cursors, setCursors] = useState([""]),
    [selected, setSelected] = useState<Row | null>(null),
    [source, setSource] = useState("ai");
  useEffect(() => {
    setCursors([""]);
    setSelected(null);
  }, [kind]);
  const ai = kind === "ai",
    p = new URLSearchParams({
      ...scope,
      kind: ai ? "" : kind,
      after: cursors.at(-1) || "",
    }),
    { data, error, loading } = useData<Page>(
      "/directory/" + (ai ? "ai-relationships" : "relationships") + "?" + p,
      refresh,
    );
  if (selected) {
    const owner = text(selected.user_id || selected.owner),
      char = text(selected.character_id || selected.character),
      pair = { user_id: owner, character_id: char },
      account = selected.owner ? selected.account_exists === true : true;
    return (
      <div className="relationship-detail">
        <div className="relationship-path">
          <button className="back-link" onClick={() => setSelected(null)}>
            <ArrowLeft size={14} />
            返回关系列表
          </button>
          <div>
            {account ? (
              <button
                className="text-button"
                onClick={() => navigate("user:" + owner)}
              >
                {userName(selected)}
              </button>
            ) : (
              <code>{owner}</code>
            )}
            <Link2 size={15} />
            <button
              className="text-button"
              onClick={() => navigate("character:" + char)}
            >
              {text(selected.character_name) || char}
            </button>
          </div>
        </div>
        <div className="relationship-overview">
          <Panel title="关系与目标">
            <Facts
              data={selected}
              keys={["subscribed", "subscribed_at", "conversation"]}
            />
            <StructuredData
              value={{
                goal_config: selected.goal_config,
                goal_progress: selected.goal_progress,
                preference: selected.preference,
              }}
            />
          </Panel>
          <Panel title="对话统计">
            <Stats
              items={[
                [ai ? "上下文消息" : "归档消息", selected.messages],
                ["用户消息", selected.user_messages],
                ["AI 消息", selected.ai_messages],
              ]}
            />
            {ai && (
              <p className="panel-note">
                未关联正式账户的历史上下文仍按原始所有者读取。
              </p>
            )}
            <RawData value={selected} />
          </Panel>
        </div>
        <Tabs
          items={[
            ["ai", "AI 上下文与运行记录"],
            ...(account
              ? [["archive", "账户归档与关系记录"] as [string, string]]
              : []),
          ]}
          selected={source}
          onChange={setSource}
        />
        <ScopedData
          key={source}
          resources={resources}
          scope={pair}
          ai={source === "ai"}
          renderResource={renderResource}
          initial={source === "ai" ? "messages" : "conversation_goals"}
        />
      </div>
    );
  }
  const isUser = !!scope.user_id;
  return (
    <section className="panel relationships-panel">
      <div className="table-toolbar">
        <h2>{isUser ? "关联角色" : "关联用户"}</h2>
        <select
          aria-label="关系范围"
          value={kind}
          onChange={(e) => setKind(e.target.value)}
        >
          <option value="">全部关系</option>
          <option value="subscribers">已订阅</option>
          <option value="conversations">已对话</option>
          <option value="ai">AI 实际上下文（含历史用户）</option>
        </select>
      </div>
      <State loading={loading} error={error} />
      {!loading && !error && (
        <>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>{isUser ? "角色" : "用户"}</th>
                  <th>订阅</th>
                  <th>{ai ? "上下文消息" : "归档消息"}</th>
                  <th>{ai ? "自动记忆" : "相处目标"}</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {data?.items.map((row) => {
                  const owner = text(row.user_id || row.owner),
                    char = text(row.character_id || row.character),
                    account = row.owner ? row.account_exists === true : true;
                  return (
                    <tr key={owner + ":" + char}>
                      <td>
                        <div className="identity-cell">
                          {(isUser || account) && (
                            <RecordAvatar
                              identity={{
                                kind: isUser ? "character" : "user",
                                id: isUser ? char : owner,
                                name: isUser
                                  ? text(row.character_name) || char
                                  : userName(row),
                              }}
                            />
                          )}
                          <div>
                            <strong>
                              {isUser
                                ? text(row.character_name) || char
                                : account
                                  ? userName(row)
                                  : owner}
                            </strong>
                            <small>
                              {isUser
                                ? char
                                : account
                                  ? text(row.starry_id)
                                  : "历史上下文"}
                            </small>
                          </div>
                        </div>
                      </td>
                      <td>
                        <span
                          className={
                            "badge " + (row.subscribed ? "positive" : "")
                          }
                        >
                          {row.subscribed ? "已订阅" : "未订阅"}
                        </span>
                      </td>
                      <td>{number(row.messages)}</td>
                      <td>
                        {ai
                          ? number(row.memories)
                          : scalar(object(row.goal_config).mode, "mode")}
                      </td>
                      <td>
                        <div className="row-actions">
                          {(isUser || account) && (
                            <button
                              className="text-button"
                              aria-label={isUser ? "角色页" : "用户页"}
                              onClick={() =>
                                navigate(
                                  (isUser ? "character:" : "user:") +
                                    (isUser ? char : owner),
                                )
                              }
                            >
                              {isUser ? "角色页" : "用户页"}
                            </button>
                          )}
                          <button
                            className="text-button"
                            onClick={() => {
                              setSelected(row);
                              setSource(ai ? "ai" : "archive");
                            }}
                          >
                            关系与记录
                            <ChevronRight size={13} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <State empty={!data?.items.length} />
        </>
      )}
      <Pager
        page={data}
        loading={loading}
        cursors={cursors}
        setCursors={setCursors}
      />
    </section>
  );
}
export function BackendIndex({
  resources,
  navigate,
  tools,
}: {
  resources: Resource[];
  navigate: (s: string) => void;
  tools: { id: string; name: string }[];
}) {
  const [q, setQ] = useState(""),
    [group, setGroup] = useState("全部"),
    list = resources.filter(
      (r) =>
        (group === "全部" || r.group === group) &&
        (r.name + " " + r.id + " " + r.description)
          .toLowerCase()
          .includes(q.toLowerCase()),
    );
  const groups = ["全部", ...new Set(resources.map((r) => r.group))];
  return (
    <>
      <Heading
        title="后台数据"
        description="查看数据、AI 运行记录及服务管理。"
      />
      <div className="backend-tools">
        {[
          { id: "overview", name: "服务与数据总览" },
          { id: "voice-timings", name: "语音耗时" },
          { id: "operations", name: "服务运行" },
          ...tools.map((t) => ({ ...t, id: "manage:" + t.id })),
        ].map((t) => (
          <button
            key={t.id}
            className="secondary"
            onClick={() => navigate(t.id)}
          >
            {t.name}
            <ChevronRight size={13} />
          </button>
        ))}
      </div>
      <section className="panel backend-catalog">
        <div className="table-toolbar">
          <SearchBox
            value={q}
            onChange={setQ}
            label="搜索后台数据"
            placeholder="搜索数据名称或用途"
          />
          <span className="muted">{list.length} 个数据分类</span>
        </div>
        <div className="filter-tabs">
          {groups.map((g) => (
            <button
              key={g}
              className={g === group ? "selected" : ""}
              onClick={() => setGroup(g)}
            >
              {g}
            </button>
          ))}
        </div>
        <div className="backend-groups">
          {list.map((r) => (
            <button
              className="catalog-item"
              key={(r.ai ? "ai:" : "") + r.id}
              onClick={() => navigate((r.ai ? "ai:" : "") + r.id)}
            >
              <span className="catalog-group">
                {r.group}
                {r.ai ? " · AI" : ""}
              </span>
              <strong>{r.name}</strong>
              <span>{r.description}</span>
              <ChevronRight size={16} />
            </button>
          ))}
        </div>
        <State empty={!list.length} />
      </section>
    </>
  );
}
