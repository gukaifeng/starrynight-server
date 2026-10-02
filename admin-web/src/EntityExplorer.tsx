import { useEffect, useState, type ReactNode } from "react";
import { Tab, TabGroup, TabList, TabPanel, TabPanels } from "@headlessui/react";
import {
  ArrowLeft,
  ArrowRight,
  ChevronRight,
  Database,
  Heart,
  Link2,
  Search,
  Users,
  X,
} from "lucide-react";
import { compact, type Resource, type Row, type Page } from "./api";
import { Json, Message, time, useData } from "./Management";
import { RecordAvatar, imageURL } from "./RecordImages";

export type EntityScope = { user_id?: string; character_id?: string };
export type ResourceRenderer = (
  resource: Resource,
  scope: EntityScope,
) => ReactNode;
export const object = (value: unknown): Row =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Row)
    : {};
const text = (v: unknown) => (typeof v === "string" ? v : "");
const number = (v: unknown) => Number(v ?? 0).toLocaleString();
const userName = (r: Row) =>
  text(object(r.profile).display_name) ||
  text(r.starry_id) ||
  text(r.username) ||
  "访客";
type DetailData = {
  entity: Row;
  stats: Row;
  settings?: Row;
  author?: Row;
  owner?: Row;
};

function Pager({
  page,
  cursors,
  loading,
  onCursors,
}: {
  page: Page | null;
  cursors: string[];
  loading: boolean;
  onCursors: (v: string[]) => void;
}) {
  return (
    <div className="pagination entity-pagination">
      <span>
        第 {cursors.length} 页 · {page?.items.length ?? 0} 条 · 游标分页
      </span>
      <button
        className="secondary"
        disabled={loading || cursors.length === 1}
        onClick={() => onCursors(cursors.slice(0, -1))}
      >
        <ArrowLeft size={14} />
        上一页
      </button>
      <button
        className="secondary"
        disabled={loading || !page?.next}
        onClick={() => onCursors([...cursors, page!.next])}
      >
        下一页
        <ArrowRight size={14} />
      </button>
    </div>
  );
}
function State({
  loading,
  error,
  empty,
}: {
  loading: boolean;
  error: string;
  empty?: boolean;
}) {
  return error ? (
    <Message text={error} />
  ) : loading ? (
    <div className="entity-state" role="status">
      正在读取当前页…
    </div>
  ) : empty ? (
    <div className="entity-state">当前范围没有记录</div>
  ) : null;
}
function Value({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="entity-value">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}
function GoalSummary({ row }: { row: Row }) {
  const config = object(row.goal_config),
    progress = object(row.goal_progress),
    bond = object(progress.bond);
  const names: Record<string, string> = {
    relationship: "关系养成",
    task: "任务陪伴",
    sandbox: "自由相处",
    strangers: "陌生人",
    pursuit: "追求",
    flirting: "暧昧",
    lovers: "恋人",
    friends: "朋友",
    mentor: "师徒",
    rivals: "宿敌",
    childhood: "青梅竹马",
    romance: "恋爱",
    friendship: "友谊",
    understanding: "彼此理解",
  };
  const label = (v: unknown) => names[text(v)] || text(v) || "未设置";
  return Object.keys(config).length ? (
    <>
      <dl>
        <Value label="相处模式">
          {label(config.mode)}
          {config.paused ? " · 已暂停" : ""}
        </Value>
        <Value label="初始关系">{label(config.initial_relation)}</Value>
        <Value label="长期方向">{label(config.long_term)}</Value>
        <Value label="本次目标">
          {text(config.short_term) || "随对话自然发展"}
        </Value>
      </dl>
      {!!Object.keys(bond).length && (
        <div className="bond-meters">
          {[
            ["familiarity", "熟悉"],
            ["trust", "信任"],
            ["affection", "好感"],
          ].map(([k, n]) => (
            <div key={k}>
              <span>{n}</span>
              <meter min={0} max={100} value={Number(bond[k] ?? 0)} />
              <b>{Number(bond[k] ?? 0).toFixed(1)}</b>
            </div>
          ))}
        </div>
      )}
      <details>
        <summary>完整目标、进度与分支</summary>
        <Json data={{ 目标: config, 进度: progress }} />
      </details>
    </>
  ) : (
    <p className="scope-note">
      尚未保存关系目标。原始推理记录可在下面查看，不推断或补造关系进度。
    </p>
  );
}
export function scopedResources(
  resources: Resource[],
  scope: EntityScope,
  ai: boolean,
) {
  return resources.filter((r) => {
    if (!!r.ai !== ai) return false;
    const user = scope.user_id,
      character = scope.character_id;
    if (ai) {
      if (["config", "prompts"].includes(r.id)) return false;
      return (
        (!user || r.fields.includes("owner") || r.id === "reply_embeddings") &&
        (!character ||
          r.fields.includes("character") ||
          ["profiles", "reply_embeddings"].includes(r.id))
      );
    }
    return (
      (!user ||
        r.fields.includes("user_id") ||
        ["users", "characters"].includes(r.id)) &&
      (!character || r.fields.includes("character_id") || r.id === "characters")
    );
  });
}

function ScopedData({
  resources,
  scope,
  ai,
  renderResource,
  initial,
}: {
  resources: Resource[];
  scope: EntityScope;
  ai: boolean;
  renderResource: ResourceRenderer;
  initial?: string;
}) {
  const list = scopedResources(resources, scope, ai);
  const [selected, setSelected] = useState(
    initial ?? (ai ? "messages" : "preferences"),
  );
  const resource = list.find((r) => r.id === selected) ?? list[0];
  return (
    <section className="scoped-data">
      <div className="scope-toolbar">
        <div>
          <Database size={16} />
          <strong>{ai ? "AI 实际运行数据" : "账户同步与内容归档"}</strong>
        </div>
        <label>
          数据分类
          <select
            aria-label={ai ? "AI 数据分类" : "账户数据分类"}
            value={resource?.id ?? ""}
            onChange={(e) => setSelected(e.target.value)}
          >
            {list.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      <p className="scope-note">
        {ai
          ? "这里是推理服务实际使用的上下文、自动记忆及预缓存；不会与 PostgreSQL 聊天归档相加。"
          : "只显示当前用户／角色范围内的记录。编辑和重置继续采用版本检查、权限控制和操作审计。"}
      </p>
      {resource ? (
        renderResource(resource, scope)
      ) : (
        <div className="entity-state">
          此范围的数据暂不可用；可到后台数据查看服务状态。
        </div>
      )}
    </section>
  );
}

function RelationshipDetail({
  row,
  resources,
  refresh,
  navigate,
  renderResource,
  back,
}: {
  row: Row;
  resources: Resource[];
  refresh: number;
  navigate: (v: string) => void;
  renderResource: ResourceRenderer;
  back: () => void;
}) {
  const scope = {
    user_id: text(row.user_id || row.owner),
    character_id: text(row.character_id || row.character),
  };
  const isAccount = row.owner ? row.account_exists === true : true;
  const [source, setSource] = useState<"archive" | "ai">(
    row.owner ? "ai" : "archive",
  );
  return (
    <div className="relationship-detail">
      <button className="text-button" onClick={back}>
        <ArrowLeft size={15} />
        返回关系列表
      </button>
      <div className="relationship-path">
        <button
          disabled={!isAccount}
          onClick={() => navigate("user:" + scope.user_id)}
        >
          <Users size={16} />
          {row.owner ? scope.user_id : userName(row)}
        </button>
        <Link2 size={16} />
        <button onClick={() => navigate("character:" + scope.character_id)}>
          <RecordAvatar
            identity={{
              kind: "character",
              id: scope.character_id,
              name: text(row.character_name) || scope.character_id,
            }}
            revision={refresh}
          />
          {text(row.character_name) || scope.character_id}
          <ChevronRight size={14} />
        </button>
      </div>
      {!isAccount && (
        <p className="scope-note">
          历史推理标识没有对应的账户 UUID，保留原始标识，不与其他账户合并。
        </p>
      )}
      <div className="relationship-overview">
        <div>
          <span>当前订阅</span>
          <strong>{row.subscribed ? "已订阅" : "未订阅"}</strong>
        </div>
        <div>
          <span>{row.owner ? "AI 上下文" : "聊天归档"}</span>
          <strong>{number(row.messages)} 条</strong>
        </div>
        <div>
          <span>消息页状态</span>
          <strong>
            {object(row.conversation).hidden ? "不显示" : "正常显示"}
          </strong>
        </div>
      </div>
      <div className="entity-info-grid">
        <section className="panel entity-info">
          <h3>关系目标与进度</h3>
          <GoalSummary row={row} />
        </section>
        <section className="panel entity-info">
          <h3>偏好与会话状态</h3>
          <Json
            data={{
              偏好: row.preference ?? null,
              会话: row.conversation ?? null,
            }}
          />
        </section>
      </div>
      <div className="source-switch" aria-label="会话数据来源">
        <button
          disabled={!isAccount}
          aria-pressed={source === "archive"}
          onClick={() => setSource("archive")}
        >
          账户归档
        </button>
        <button aria-pressed={source === "ai"} onClick={() => setSource("ai")}>
          AI 上下文与运行记录
        </button>
      </div>
      {source === "archive" && isAccount ? (
        <ScopedData
          resources={resources}
          scope={scope}
          ai={false}
          initial="messages"
          renderResource={renderResource}
        />
      ) : (
        <WorkerData
          resources={resources}
          owner={scope.user_id}
          character={scope.character_id}
          renderResource={renderResource}
        />
      )}
    </div>
  );
}

// A historical worker owner is not always a registered UUID. Keep it exact.
function WorkerData({
  resources,
  owner,
  character,
  renderResource,
}: {
  resources: Resource[];
  owner?: string;
  character?: string;
  renderResource: ResourceRenderer;
}) {
  return (
    <ScopedData
      resources={resources}
      scope={{ user_id: owner, character_id: character }}
      ai
      renderResource={renderResource}
    />
  );
}

function WorkerSummary({
  scope,
  refresh,
}: {
  scope: EntityScope;
  refresh: number;
}) {
  const p = new URLSearchParams({
    ...(scope.user_id ? { owner: scope.user_id } : {}),
    ...(scope.character_id ? { character: scope.character_id } : {}),
  });
  const { data, error, loading } = useData<Row>(
    "/ai/console/entity-summary?" + p.toString(),
    refresh,
  );
  return (
    <section className="panel worker-summary">
      <div>
        <strong>AI 实际运行</strong>
        <small>独立统计，不与账户归档相加</small>
      </div>
      {error ? (
        <span className="scope-note">AI 汇总暂不可用；账户数据仍可查看。</span>
      ) : loading ? (
        <span className="scope-note">正在读取当前对象的推理统计…</span>
      ) : (
        <>
          <span>
            <b>{number(data?.messages)}</b>上下文消息
          </span>
          <span>
            <b>{number(data?.memories)}</b>自动记忆
          </span>
          <span>
            <b>{number(data?.requests)}</b>推理请求
          </span>
          <span>
            <b>{number(data?.reaction_drafts)}</b>场景预缓存
          </span>
          <details>
            <summary>更多统计</summary>
            <Json data={data} />
          </details>
        </>
      )}
    </section>
  );
}

function Relationships({
  scope,
  resources,
  refresh,
  navigate,
  renderResource,
}: {
  scope: EntityScope;
  resources: Resource[];
  refresh: number;
  navigate: (v: string) => void;
  renderResource: ResourceRenderer;
}) {
  const [kind, setKind] = useState(""),
    [cursors, setCursors] = useState([""]),
    [focused, setFocused] = useState<Row | null>(null);
  const worker = kind === "ai";
  const query = new URLSearchParams({
    ...scope,
    ...(worker ? {} : { kind }),
    after: cursors.at(-1)!,
  });
  const { data, error, loading } = useData<Page>(
    (worker ? "/directory/ai-relationships?" : "/directory/relationships?") +
      query.toString(),
    refresh,
  );
  if (focused)
    return (
      <RelationshipDetail
        row={focused}
        resources={resources}
        refresh={refresh}
        navigate={navigate}
        renderResource={renderResource}
        back={() => setFocused(null)}
      />
    );
  return (
    <section className="panel relationships-panel">
      <div className="table-toolbar">
        <div>
          <h2>
            {scope.user_id ? "这个用户与角色的关系" : "这个角色与用户的关系"}
          </h2>
          <p className="scope-note">
            选择一组关系，查看目标、偏好、对话、记忆和推理明细。
          </p>
        </div>
        <label>
          关系范围
          <select
            aria-label="关系范围"
            value={kind}
            onChange={(e) => {
              setKind(e.target.value);
              setCursors([""]);
            }}
          >
            <option value="">全部账户关系</option>
            <option value="subscribers">当前订阅</option>
            <option value="conversations">账户会话</option>
            <option value="ai">AI 推理会话</option>
          </select>
        </label>
      </div>
      <State loading={loading} error={error} empty={!data?.items.length} />
      {!loading && !error && (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>{scope.user_id ? "角色" : "用户"}</th>
                <th>{worker ? "推理记录" : "订阅／关系"}</th>
                <th>聊天条数</th>
                <th>最近会话</th>
                <th>关联页面</th>
              </tr>
            </thead>
            <tbody>
              {data?.items.map((row) => {
                const uid = text(row.user_id || row.owner),
                  cid = text(row.character_id || row.character),
                  name = scope.user_id
                    ? text(row.character_name) || cid
                    : worker && !row.account_exists
                      ? uid
                      : userName(row);
                return (
                  <tr key={uid + ":" + cid}>
                    <td>
                      <button
                        className="entity-inline"
                        onClick={() => setFocused(row)}
                      >
                        <RecordAvatar
                          identity={{
                            kind: scope.user_id ? "character" : "user",
                            id: scope.user_id ? cid : uid,
                            name,
                          }}
                          revision={refresh}
                        />
                        <span>
                          <strong>{name}</strong>
                          <small>
                            {scope.user_id ? cid : text(row.starry_id) || uid}
                          </small>
                        </span>
                      </button>
                    </td>
                    <td>
                      <span className="tag">
                        {worker
                          ? `自动记忆 ${number(row.memories)}`
                          : row.subscribed
                            ? "已订阅"
                            : "未订阅"}
                      </span>
                      {!!row.goal_config && (
                        <small className="relation-goal">
                          {compact(
                            object(row.goal_config).mode ??
                              object(row.goal_config).long_term_goal,
                          )}
                        </small>
                      )}
                    </td>
                    <td className="mono">{number(row.messages)}</td>
                    <td>
                      {time(
                        worker
                          ? row.last_message_at
                          : object(row.conversation).updated_at,
                      )}
                    </td>
                    <td>
                      <div className="relation-actions">
                        <button
                          className="text-button"
                          onClick={() => setFocused(row)}
                        >
                          关系与记录
                          <ChevronRight size={13} />
                        </button>
                        <button
                          className="text-button"
                          onClick={() =>
                            navigate(
                              scope.user_id
                                ? "character:" + cid
                                : "user:" + uid,
                            )
                          }
                          disabled={
                            worker && !scope.user_id && !row.account_exists
                          }
                        >
                          {scope.user_id ? "角色页" : "用户页"}
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <Pager
        page={data}
        cursors={cursors}
        loading={loading}
        onCursors={setCursors}
      />
    </section>
  );
}

function EntityDetail({
  kind,
  id,
  resources,
  refresh,
  navigate,
  renderResource,
}: {
  kind: "users" | "characters";
  id: string;
  resources: Resource[];
  refresh: number;
  navigate: (v: string) => void;
  renderResource: ResourceRenderer;
}) {
  const { data, error, loading } = useData<DetailData>(
    "/directory/" + kind + "/" + encodeURIComponent(id),
    refresh,
  );
  const isUser = kind === "users",
    scope = isUser ? { user_id: id } : { character_id: id };
  if (loading || error || !data)
    return (
      <>
        <button
          className="text-button"
          onClick={() =>
            navigate(isUser ? "directory:users" : "directory:characters")
          }
        >
          <ArrowLeft size={14} />
          返回目录
        </button>
        <State loading={loading} error={error} empty={!data} />
      </>
    );
  const row = data.entity,
    profile = object(row.profile),
    name = isUser ? userName(row) : text(row.name) || id;
  const metrics = isUser
    ? [
        ["subscriptions", "订阅角色"],
        ["conversations", "账户会话"],
        ["messages", "归档消息"],
        ["created_characters", "创作角色"],
      ]
    : [
        ["subscriptions", "当前订阅者"],
        ["chatters", "归档聊天用户"],
        ["messages", "归档消息"],
        ["ai_messages", "AI 归档回复"],
      ];
  return (
    <div className="entity-detail">
      <button
        className="text-button entity-back"
        onClick={() =>
          navigate(isUser ? "directory:users" : "directory:characters")
        }
      >
        <ArrowLeft size={14} />
        返回{isUser ? "用户" : "角色"}目录
      </button>
      <section className="panel entity-hero">
        {!isUser && (
          <img
            className="entity-cover"
            src={imageURL({ kind: "character", id, name }, "cover", refresh)}
            alt={name + "的封面"}
            onError={(e) => {
              e.currentTarget.style.visibility = "hidden";
            }}
          />
        )}
        <div className="entity-hero-main">
          <RecordAvatar
            identity={{ kind: isUser ? "user" : "character", id, name }}
            className="entity-large-avatar"
            revision={refresh}
          />
          <div>
            <div className="eyebrow">
              {isUser ? "ACCOUNT / RELATIONSHIPS" : "CHARACTER / CONNECTIONS"}
            </div>
            <h1>{name}</h1>
            <p>
              {isUser
                ? text(profile.bio) || "这个用户的资料、关系与相遇。"
                : text(row.description) || "角色资料与用户关系。"}
            </p>
            <div className="entity-identifiers">
              <code>{isUser ? text(row.starry_id) || "未分配星夜号" : id}</code>
              <span className="tag">
                {isUser
                  ? row.guest
                    ? "游客账户"
                    : "注册账户"
                  : row.deleted
                    ? "已下架"
                    : row.visibility === "public"
                      ? "公开角色"
                      : row.visibility === "private"
                        ? "私人角色"
                        : "未列出角色"}
              </span>
            </div>
          </div>
        </div>
        <div className="entity-metrics">
          {metrics.map(([key, label]) => (
            <div key={key}>
              <strong>{number(data.stats[key])}</strong>
              <span>{label}</span>
            </div>
          ))}
        </div>
      </section>
      <WorkerSummary scope={scope} refresh={refresh} />
      <TabGroup className="entity-tabs">
        <TabList>
          {[
            "概览",
            isUser ? "角色与羁绊" : "订阅者与对话用户",
            isUser ? "账户全部数据" : "角色全部数据",
            "AI 运行数据",
          ].map((label) => (
            <Tab key={label}>{label}</Tab>
          ))}
        </TabList>
        <TabPanels>
          <TabPanel>
            <div className="entity-info-grid">
              <section className="panel entity-info">
                <h2>{isUser ? "账户资料" : "角色资料"}</h2>
                <dl>
                  <Value label={isUser ? "内部 UUID" : "角色 ID"}>
                    <code>{id}</code>
                  </Value>
                  <Value label={isUser ? "登录账号" : "作者"}>
                    {isUser
                      ? text(row.username) || "游客尚未设置"
                      : text(object(data.author?.data).name) ||
                        text(row.author_id)}
                  </Value>
                  <Value label={isUser ? "注册时间" : "更新时间"}>
                    {time(isUser ? row.created_at : row.updated_at)}
                  </Value>
                  <Value label="资料版本">{number(row.version)}</Value>
                  {!isUser && !!data.owner && (
                    <Value label="创建用户">
                      <button
                        className="text-button"
                        onClick={() => navigate("user:" + text(data.owner!.id))}
                      >
                        {userName(data.owner!)}
                        <ChevronRight size={13} />
                      </button>
                    </Value>
                  )}
                  {!!data.author?.user_id && (
                    <Value label="作者账户">
                      <button
                        className="text-button"
                        onClick={() =>
                          navigate("user:" + text(data.author!.user_id))
                        }
                      >
                        {text(data.author!.user_id)}
                        <ChevronRight size={13} />
                      </button>
                    </Value>
                  )}
                </dl>
                <details>
                  <summary>完整{isUser ? "个人资料" : "角色元数据"}</summary>
                  <Json data={isUser ? row.profile : row.data} />
                </details>
              </section>
              <section className="panel entity-info">
                <h2>{isUser ? "全局设置与创作者资料" : "作者与来源"}</h2>
                <Json
                  data={
                    isUser
                      ? {
                          全局设置: data.settings ?? null,
                          作者资料: data.author ?? null,
                        }
                      : {
                          作者: data.author,
                          来源角色: row.base_id,
                          角色数据: row.data,
                        }
                  }
                />
              </section>
              <section className="panel entity-info entity-accounting">
                <Heart size={20} />
                <div>
                  <h3>从一段关系进入全部记录</h3>
                  <p>
                    订阅、聊天、目标进度和记忆按同一个用户与角色组合查看。账户归档和
                    AI 实际上下文分别展示，统计口径可追溯。
                  </p>
                </div>
              </section>
            </div>
          </TabPanel>
          <TabPanel>
            <Relationships
              scope={scope}
              resources={resources}
              refresh={refresh}
              navigate={navigate}
              renderResource={renderResource}
            />
          </TabPanel>
          <TabPanel>
            <ScopedData
              resources={resources}
              scope={scope}
              ai={false}
              renderResource={renderResource}
              initial={isUser ? "users" : "characters"}
            />
          </TabPanel>
          <TabPanel>
            <ScopedData
              resources={resources}
              scope={scope}
              ai
              renderResource={renderResource}
              initial={isUser ? "messages" : "profiles"}
            />
          </TabPanel>
        </TabPanels>
      </TabGroup>
    </div>
  );
}

export function EntityExplorer({
  kind,
  id,
  resources,
  refresh,
  navigate,
  renderResource,
}: {
  kind: "users" | "characters";
  id?: string;
  resources: Resource[];
  refresh: number;
  navigate: (v: string) => void;
  renderResource: ResourceRenderer;
}) {
  const [q, setQ] = useState(""),
    [query, setQuery] = useState(""),
    [filter, setFilter] = useState(""),
    [size, setSize] = useState("25"),
    [cursors, setCursors] = useState([""]);
  useEffect(() => {
    const t = setTimeout(() => {
      setQuery(q.trim());
      setCursors([""]);
    }, 300);
    return () => clearTimeout(t);
  }, [q]);
  // Directory and detail are separate components: detail navigation never
  // fetches the directory (or every count in the database) in the background.
  return id ? (
    <EntityDetail
      key={kind + ":" + id}
      kind={kind}
      id={id}
      resources={resources}
      refresh={refresh}
      navigate={navigate}
      renderResource={renderResource}
    />
  ) : (
    <EntityDirectory
      kind={kind}
      q={q}
      setQ={setQ}
      query={query}
      filter={filter}
      setFilter={(v) => {
        setFilter(v);
        setCursors([""]);
      }}
      size={size}
      setSize={(v) => {
        setSize(v);
        setCursors([""]);
      }}
      cursors={cursors}
      setCursors={setCursors}
      refresh={refresh}
      navigate={navigate}
    />
  );
}

function EntityDirectory({
  kind,
  q,
  setQ,
  query,
  filter,
  setFilter,
  size,
  setSize,
  cursors,
  setCursors,
  refresh,
  navigate,
}: {
  kind: "users" | "characters";
  q: string;
  setQ: (v: string) => void;
  query: string;
  filter: string;
  setFilter: (v: string) => void;
  size: string;
  setSize: (v: string) => void;
  cursors: string[];
  setCursors: (v: string[]) => void;
  refresh: number;
  navigate: (v: string) => void;
}) {
  const isUser = kind === "users",
    p = new URLSearchParams({
      q: query,
      kind: filter,
      limit: size,
      after: cursors.at(-1)!,
    });
  const { data, error, loading } = useData<Page>(
    "/directory/" + kind + "?" + p.toString(),
    refresh,
  );
  return (
    <div className="entity-directory">
      <div className="page-heading">
        <div>
          <div className="eyebrow">
            {isUser ? "PEOPLE, WITH A STORY" : "CHARACTERS, WITH CONNECTIONS"}
          </div>
          <h1>{isUser ? "用户" : "角色"}</h1>
          <p>
            {isUser
              ? "从一个账户，看见资料、偏好和每一段关系。"
              : "从一个角色，看见设定、订阅者和每一次对话。"}
          </p>
        </div>
        <div className="directory-mode">
          <span className="live-dot" />
          按需查询 · 每页最多 50 条
        </div>
      </div>
      <section className="panel">
        <div className="table-toolbar directory-toolbar">
          <label className="search-box">
            <Search size={16} />
            <input
              aria-label={isUser ? "搜索用户" : "搜索角色"}
              placeholder={
                isUser ? "星夜号、用户名、昵称或完整 UUID…" : "角色名称或 ID…"
              }
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
            {q && (
              <button aria-label="清除目录搜索" onClick={() => setQ("")}>
                <X size={14} />
              </button>
            )}
          </label>
          {isUser && (
            <select
              aria-label="账户类型"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            >
              <option value="">全部用户</option>
              <option value="registered">注册用户</option>
              <option value="guest">游客</option>
            </select>
          )}
          <select
            aria-label="每页数量"
            value={size}
            onChange={(e) => setSize(e.target.value)}
          >
            {[10, 25, 50].map((n) => (
              <option value={n} key={n}>
                {n} 条／页
              </option>
            ))}
          </select>
        </div>
        <State loading={loading} error={error} empty={!data?.items.length} />
        {!loading && !error && (
          <div className="table-scroll">
            <table className="entity-directory-table">
              <thead>
                <tr>
                  <th>{isUser ? "用户" : "角色"}</th>
                  <th>{isUser ? "星夜号／账号" : "作者"}</th>
                  <th>状态</th>
                  <th>{isUser ? "注册时间" : "更新时间"}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data?.items.map((row) => {
                  const id = text(row.id),
                    name = isUser ? userName(row) : text(row.name);
                  const open = () =>
                    navigate((isUser ? "user:" : "character:") + id);
                  return (
                    <tr
                      key={id}
                      data-entity-id={id}
                      tabIndex={0}
                      onClick={open}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") open();
                      }}
                      aria-label={"查看" + name}
                    >
                      <td>
                        <div className="record-identity">
                          <RecordAvatar
                            identity={{
                              kind: isUser ? "user" : "character",
                              id,
                              name,
                            }}
                            revision={`${row.version}:${refresh}`}
                          />
                          <span>
                            <strong>{name}</strong>
                            <small className="mono">
                              {isUser ? id : text(row.description) || id}
                            </small>
                          </span>
                        </div>
                      </td>
                      <td>
                        {isUser ? (
                          <>
                            <strong className="mono">
                              {text(row.starry_id) || "—"}
                            </strong>
                            <small className="cell-subtitle">
                              {text(row.username) || "游客账户"}
                            </small>
                          </>
                        ) : (
                          text(row.author_name) || text(row.author_id)
                        )}
                      </td>
                      <td>
                        <span
                          className={
                            "tag " +
                            (!row.guest && !row.deleted ? "tag-good" : "")
                          }
                        >
                          {isUser
                            ? row.guest
                              ? "游客"
                              : "注册"
                            : row.deleted
                              ? "已下架"
                              : row.visibility === "public"
                                ? "公开"
                                : row.visibility === "private"
                                  ? "私人"
                                  : "未列出"}
                        </span>
                      </td>
                      <td>{time(isUser ? row.created_at : row.updated_at)}</td>
                      <td>
                        <ChevronRight size={15} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <Pager
          page={data}
          cursors={cursors}
          loading={loading}
          onCursors={setCursors}
        />
      </section>
      <p className="directory-footnote">
        只读取当前页，不计算整库总数。打开详情后按需读取当前对象的关系与统计。
      </p>
    </div>
  );
}

export function BackendIndex({
  resources,
  owner,
  navigate,
  tools,
}: {
  resources: Resource[];
  owner: boolean;
  navigate: (v: string) => void;
  tools: { id: string; name: string }[];
}) {
  const groups = ["对话", "AI", "内容", "账户", "运营", "系统", "管理"];
  return (
    <div className="backend-index">
      <div className="page-heading">
        <div>
          <div className="eyebrow">BEHIND EVERY ENCOUNTER</div>
          <h1>后台数据</h1>
          <p>
            数据库、AI 会话与运行管理。账户与角色的详细信息也可以从这里追溯。
          </p>
        </div>
        <button className="secondary" onClick={() => navigate("overview")}>
          系统总览
          <ArrowRight size={15} />
        </button>
      </div>
      <div className="backend-groups">
        {groups.map((group) => (
          <section className="panel backend-group" key={group}>
            <div className="eyebrow">
              {group === "AI"
                ? "INTELLIGENCE"
                : group === "系统"
                  ? "DATABASE"
                  : "DATA"}
            </div>
            <h2>
              {group === "对话"
                ? "对话与关系归档"
                : group === "AI"
                  ? "AI 推理与语音"
                  : group === "系统"
                    ? "数据库与同步"
                    : group}
            </h2>
            {resources
              .filter((r) => r.group === group)
              .map((r) => (
                <button
                  key={(r.ai ? "ai:" : "") + r.id}
                  onClick={() => navigate((r.ai ? "ai:" : "") + r.id)}
                >
                  <span>
                    <strong>{r.name}</strong>
                    <small>{r.description}</small>
                  </span>
                  <ChevronRight size={14} />
                </button>
              ))}
          </section>
        ))}
      </div>
      <section className="panel backend-operations">
        <div>
          <div className="eyebrow">OPERATIONS</div>
          <h2>服务器管理</h2>
          <p>
            {owner
              ? "配置、资源、备份、缓存与维护，保留现有操作权限。"
              : "当前为受限账户，服务器写操作仅对所有者开放。"}
          </p>
        </div>
        <div>
          {owner &&
            tools.map((t) => (
              <button
                className="secondary"
                key={t.id}
                onClick={() => navigate("manage:" + t.id)}
              >
                {t.name}
                <ChevronRight size={13} />
              </button>
            ))}
          <button className="secondary" onClick={() => navigate("operations")}>
            服务运行
            <ChevronRight size={13} />
          </button>
        </div>
      </section>
    </div>
  );
}
