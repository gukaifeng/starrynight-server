import { useCallback, useEffect, useRef, useState } from "react";
import { VoiceTimings } from "./VoiceTimings";
import {
  Dialog,
  DialogPanel,
  DialogTitle,
  Tab,
  TabGroup,
  TabList,
  TabPanel,
  TabPanels,
  Menu,
  MenuButton,
  MenuItems,
  MenuItem,
} from "@headlessui/react";
import {
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  BookOpen,
  Check,
  ChevronRight,
  Copy,
  Database,
  Layers,
  LogOut,
  Menu as MenuIcon,
  MessageCircle,
  Plus,
  RefreshCw,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  Users,
  Volume2,
  X,
} from "lucide-react";
import {
  api,
  compact,
  editableValues,
  keysOf,
  resourcePath,
  setCSRF,
  type AdminUser,
  type Page,
  type Resource,
  type Row,
} from "./api";

import { Management, tools as managementTools } from "./Management";
import {
  RecordAvatar,
  RecordGallery,
  RecordReference,
  recordIdentity,
} from "./RecordImages";

const labels: Record<string, string> = {
  appearance_facts: "外观事实",
  identity: "身份说明",
  values: "价值观",
  knowledge_boundary: "知识边界",
  forbidden_patterns: "表达禁区",
  relationship_style: "关系风格",
  hotwords: "识别热词",
  secrets: "私有设定",
  gender: "性别",
  age: "年龄",
  voice_revision: "音色版本",
  profile_revision: "设定版本",
  max_daily_calls: "每天对话调用上限",
  max_daily_tts_characters: "每天声音字符上限",
  max_daily_asr_seconds: "每天识别秒数上限",
  max_voice_designs: "音色设计次数上限",
  narration_timeout_seconds: "描写规划超时（秒）",
  performance_timeout_seconds: "动作规划超时（秒）",
  enable_test_inspector: "允许测试检查器",
  confirmed_distribution_rights: "已确认全部资源的再分发权",
  occupation: "职业",
  world: "世界背景",
  personality: "性格",
  background: "成长背景",
  speaking_style: "说话风格",
  scene: "当前场景",
  voice_prompt: "音色设计",
  voice_delivery: "声音演绎",
  preview_text: "音色试听文本",
  dialogue_language: "对话语言",
  scenarios: "情景模式",
  PLANNER: "完整对话规划",
  CORE_PLANNER: "核心语音规划",
  NARRATOR: "心理与动作描写",
  PERFORMER: "表情动作规划",
  REPLY_LENGTH: "回复长度规则",
  character_model: "角色对话模型",
  suggestions_model: "接话预测模型",
  translation_model: "翻译模型",
  tts_model: "声音合成模型",
  asr_model: "语音识别模型",
  paid_enabled: "允许付费调用",
  enforce_conversation_limits: "启用每日用量限制",
  reaction_pool_size: "每场景缓存数量",
  reaction_pool_ttl_seconds: "互动缓存有效期（秒）",
  entry_pool_ttl_seconds: "问候缓存有效期（秒）",
  id: "标识",
  user_id: "账户 UUID",
  character_id: "角色 ID",
  author_id: "作者 ID",
  owner_id: "所有者",
  base_id: "来源角色",
  username: "登录账号",
  starry_id: "星夜号",
  profile: "个人资料",
  data: "内容",
  name: "名称",
  description: "介绍",
  visibility: "可见性",
  version: "版本",
  created_at: "创建时间",
  updated_at: "更新时间",
  role: "权限",
  disabled: "停用",
  hidden: "不显示",
  pinned: "置顶",
  text: "正文",
  config: "目标配置",
  state: "状态",
  content: "内容",
  importance: "记忆权重",
  distributable: "允许分发",
  platform: "平台",
  manifest: "资源清单",
  kind: "类型",
  progress: "关系进度",
  password: "新密码",
  display_name: "显示名称",
  avatar: "头像",
  cover: "封面",
  bio: "简介",
  content_type: "文件格式",
  category: "分类",
  release_id: "发布 ID",
  capabilities: "模型能力",
  session_epoch: "会话版本",
  occurred_at: "操作时间",
  action: "操作",
  outcome: "结果",
  actor_name: "操作者",
  target: "目标",
  request_id: "请求 ID",
  _rowid: "记录序号",
};
const actionLabels: Record<string, string> = {
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
const groups = ["内容", "账户", "对话", "AI", "运营", "系统", "管理"];
const icons: Record<string, typeof Users> = {
  内容: Layers,
  账户: Users,
  对话: MessageCircle,
  AI: Sparkles,
  运营: BookOpen,
  系统: Database,
  管理: ShieldCheck,
};
type Overview = {
  counts: Record<string, number>;
  services: Record<string, boolean>;
  time: string;
};
type Confirmation = {
  title: string;
  description: string;
  danger?: boolean;
  password?: boolean;
  run: (password: string) => Promise<void>;
};
type Service = {
  id: string;
  ActiveState?: string;
  SubState?: string;
  MemoryCurrent?: string;
  MainPID?: string;
};
function Mark({ className = "" }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 44 44"
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M30 6a17 17 0 1 0 8 26A18 18 0 0 1 30 6Z"
        stroke="currentColor"
        strokeWidth="1.5"
      />
      <path d="m28 16 2-6 2 6 6 2-6 2-2 6-2-6-6-2 6-2Z" fill="currentColor" />
    </svg>
  );
}
function ErrorNote({ text }: { text: string }) {
  return (
    <div role="alert" className="error-note">
      {text}
    </div>
  );
}
function Empty({ text }: { text: string }) {
  return (
    <div className="empty">
      <Layers size={25} />
      <p>{text}</p>
      <span>搜索其他关键词，或切换到相关分类。</span>
    </div>
  );
}
function Tag({
  children,
  good = false,
}: {
  children: React.ReactNode;
  good?: boolean;
}) {
  return <span className={"tag " + (good ? "tag-good" : "")}>{children}</span>;
}
function Login({ onLogin }: { onLogin: (user: AdminUser) => void }) {
  const [username, setUsername] = useState("owner"),
    [password, setPassword] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  async function login(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await api<{ user: AdminUser; csrf: string }>("/login", {
        method: "POST",
        body: JSON.stringify({ username, password }),
      });
      setCSRF(result.csrf);
      onLogin(result.user);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="login-shell">
      <div className="login-world">
        <Mark />
        <div className="eyebrow">STARRY NIGHT / CONTROL ROOM</div>
        <h1>
          星夜的每一次相遇，
          <br />
          都在这里照看。
        </h1>
        <p>
          角色、记忆与声音。
          <br />
          让每个细节都有迹可循。
        </p>
        <div className="orbit-art" aria-hidden="true">
          <i />
          <i />
          <i />
          <b />
        </div>
        <span className="login-foot">星夜 · 服务端控制室</span>
      </div>
      <div className="login-form">
        <div className="eyebrow">管理账户</div>
        <h2>回到控制室</h2>
        <p>使用独立管理员账号登录。</p>
        <form onSubmit={login}>
          <label>
            账号
            <input
              name="username"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              maxLength={32}
            />
          </label>
          <label>
            密码
            <input
              name="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              maxLength={128}
            />
          </label>
          {error && <ErrorNote text={error} />}
          <button className="primary" disabled={busy}>
            {busy ? "正在验证…" : "进入控制室"}
            <ArrowRight size={17} />
          </button>
        </form>
        <div className="login-security">
          <ShieldCheck size={17} />
          <span>独立权限 · 可撤销会话 · 操作留痕</span>
        </div>
      </div>
    </main>
  );
}

export default function App() {
  const [user, setUser] = useState<AdminUser | null>(null),
    [checking, setChecking] = useState(true),
    [resources, setResources] = useState<Resource[]>([]),
    [view, setView] = useState("overview"),
    [overview, setOverview] = useState<Overview | null>(null),
    [error, setError] = useState(""),
    [toast, setToast] = useState(""),
    [refresh, setRefresh] = useState(0),
    [nav, setNav] = useState(false),
    [confirm, setConfirm] = useState<Confirmation | null>(null),
    [confirmedPassword, setConfirmedPassword] = useState(""),
    [actionBusy, setActionBusy] = useState(false),
    [actionError, setActionError] = useState("");
  const load = useCallback(async () => {
    const outcomes = await Promise.allSettled([
      api<Resource[]>("/resources"),
      api<Resource[]>("/ai/console/resources"),
      api<Overview>("/overview"),
    ]);
    const base = outcomes[0];
    if (base.status === "rejected") throw base.reason;
    let all = base.value;
    const ai = outcomes[1];
    if (ai.status === "fulfilled")
      all = all.concat(ai.value.map((r) => ({ ...r, ai: true })));
    else setError("AI 管理暂不可用；账户与内容管理可以继续使用。");
    setResources(all);
    if (outcomes[2].status === "fulfilled") setOverview(outcomes[2].value);
  }, []);
  useEffect(() => {
    const expired = () => {
      setCSRF("");
      setUser(null);
    };
    window.addEventListener("admin-session-expired", expired);
    return () => window.removeEventListener("admin-session-expired", expired);
  }, []);
  useEffect(() => {
    api<{ user: AdminUser; csrf: string }>("/session")
      .then((data) => {
        setCSRF(data.csrf);
        setUser(data.user);
      })
      .catch(() => {})
      .finally(() => setChecking(false));
  }, []);
  useEffect(() => {
    if (user) load().catch((e) => setError(e.message));
  }, [user, load, refresh]);
  useEffect(() => {
    if (!toast) return;
    const id = setTimeout(() => setToast(""), 4500);
    return () => clearTimeout(id);
  }, [toast]);
  const ask = (c: Confirmation) => {
    setConfirmedPassword("");
    setActionError("");
    setConfirm(c);
  };
  const changed = () => {
    setRefresh((n) => n + 1);
    setToast("已完成，最新数据已刷新");
  };
  const choose = (value: string) => {
    setView(value);
    setNav(false);
    setError("");
  };
  async function perform() {
    if (!confirm) return;
    setActionBusy(true);
    setActionError("");
    try {
      await confirm.run(confirmedPassword);
      setConfirm(null);
      changed();
    } catch (e) {
      setActionError((e as Error).message);
    } finally {
      setActionBusy(false);
    }
  }
  if (checking)
    return (
      <div className="session-check">
        <Mark />
        <p>正在连接星夜控制室…</p>
      </div>
    );
  if (!user) return <Login onLogin={setUser} />;
  const current = resources.find((r) => (r.ai ? "ai:" : "") + r.id === view);
  return (
    <div className="app-shell">
      <aside className={"sidebar " + (nav ? "is-open" : "")}>
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            choose("overview");
          }}
        >
          <Mark />
          <div>
            <strong>星夜</strong>
            <span>CONTROL ROOM</span>
          </div>
        </a>
        <nav aria-label="管理导航">
          <button
            className={"nav-item " + (view === "overview" ? "active" : "")}
            onClick={() => choose("overview")}
          >
            <Sparkles size={17} />
            总览
            <span className="nav-orbit" />
          </button>
          {groups.map((group) => {
            const Icon = icons[group];
            const list = resources.filter((r) => r.group === group);
            return (
              list.length > 0 && (
                <div className="nav-group" key={group}>
                  <div className="nav-caption">
                    <Icon size={13} />
                    {group}
                  </div>
                  {list.map((r) => {
                    const id = (r.ai ? "ai:" : "") + r.id;
                    return (
                      <button
                        key={id}
                        aria-label={r.name}
                        className={
                          "nav-resource " + (view === id ? "active" : "")
                        }
                        onClick={() => choose(id)}
                      >
                        {r.name}
                        {r.id === "characters" && overview && (
                          <small>{overview.counts.characters}</small>
                        )}
                      </button>
                    );
                  })}
                </div>
              )
            );
          })}
          {user.role === "owner" && (
            <div className="nav-group">
              <div className="nav-caption">
                <Database size={13} />
                服务器管理
              </div>
              {managementTools.map((t) => (
                <button
                  key={t.id}
                  aria-label={t.name}
                  className={
                    "nav-resource " +
                    (view === "manage:" + t.id ? "active" : "")
                  }
                  onClick={() => choose("manage:" + t.id)}
                >
                  {t.name}
                </button>
              ))}
            </div>
          )}
          <button
            className={"nav-item " + (view === "operations" ? "active" : "")}
            onClick={() => choose("operations")}
          >
            <Settings2 size={16} />
            服务运行
          </button>
        </nav>
        <div className="operator">
          <span className="operator-avatar">
            {user.username.slice(0, 1).toUpperCase()}
          </span>
          <div>
            <strong>{user.username}</strong>
            <small>
              {user.role === "owner"
                ? "所有者"
                : user.role === "editor"
                  ? "编辑者"
                  : "观察者"}
            </small>
          </div>
          <button
            title="退出管理账户"
            aria-label="退出管理账户"
            onClick={async () => {
              try {
                await api("/logout", { method: "POST", body: "{}" });
                setUser(null);
              } catch (e) {
                setError((e as Error).message);
              }
            }}
          >
            <LogOut size={16} />
          </button>
        </div>
      </aside>
      {nav && (
        <button
          className="nav-backdrop"
          aria-label="关闭导航"
          onClick={() => setNav(false)}
        />
      )}
      <main className="workspace">
        <header className="topline">
          <button
            className="mobile-nav icon-button"
            onClick={() => setNav(true)}
            aria-label="打开导航"
          >
            <MenuIcon size={20} />
          </button>
          <span>{current?.group ?? "星夜服务"}</span>
          <ChevronRight size={12} />
          <span>
            {current?.name ??
              managementTools.find((t) => "manage:" + t.id === view)?.name ??
              (view === "operations" ? "运行状态" : "控制室")}
          </span>
          <div className="topline-right">
            <span className="live-dot" />
            安全管理入口
            <button
              className="icon-button"
              aria-label="刷新数据"
              onClick={() => {
                setError("");
                setRefresh((n) => n + 1);
              }}
            >
              <RefreshCw size={16} />
            </button>
          </div>
        </header>
        {error && <ErrorNote text={error} />}
        <div className="page-content">
          {view === "overview" ? (
            <Dashboard
              overview={overview}
              resources={resources}
              choose={choose}
            />
          ) : view === "operations" ? (
            <Operations user={user} refresh={refresh} ask={ask} />
          ) : view.startsWith("manage:") && user.role === "owner" ? (
            <Management
              key={view}
              view={view.slice(7)}
              refresh={refresh}
              ask={ask}
            />
          ) : view === "ai:voice_traces" ? (
            <VoiceTimings refresh={refresh} />
          ) : current ? (
            <ResourceWorkspace
              key={view}
              resource={current}
              user={user}
              refresh={refresh}
              ask={ask}
              onChanged={changed}
            />
          ) : (
            <Empty text="该分类暂不可用，刷新后重试" />
          )}
        </div>
        <footer className="workspace-foot">
          <span>STARRY NIGHT</span>
          <span>管理操作保留审计记录 · 时间按本地时区显示</span>
        </footer>
      </main>
      <Dialog
        open={!!confirm}
        onClose={() => {
          if (!actionBusy) setConfirm(null);
        }}
        className="dialog-root"
      >
        <div className="dialog-shade" />
        <div className="dialog-position">
          <DialogPanel className="confirm-panel">
            <div className="eyebrow">确认管理操作</div>
            <DialogTitle as="h2">{confirm?.title}</DialogTitle>
            <p>{confirm?.description}</p>
            {confirm?.password && (
              <label>
                新密码
                <input
                  type="password"
                  autoComplete="new-password"
                  value={confirmedPassword}
                  onChange={(e) => setConfirmedPassword(e.target.value)}
                  minLength={12}
                  maxLength={128}
                  placeholder="至少 12 字符"
                />
              </label>
            )}
            {actionError && <ErrorNote text={actionError} />}
            <div className="form-actions">
              <button
                className="secondary"
                disabled={actionBusy}
                onClick={() => setConfirm(null)}
              >
                取消
              </button>
              <button
                className={confirm?.danger ? "danger" : "primary"}
                onClick={perform}
                disabled={
                  actionBusy ||
                  (!!confirm?.password && confirmedPassword.length < 12)
                }
              >
                {actionBusy ? "正在处理…" : "确认执行"}
              </button>
            </div>
          </DialogPanel>
        </div>
      </Dialog>
      {toast && (
        <div role="status" className="toast">
          <Check size={16} />
          {toast}
        </div>
      )}
    </div>
  );
}

function Dashboard({
  overview,
  resources,
  choose,
}: {
  overview: Overview | null;
  resources: Resource[];
  choose: (id: string) => void;
}) {
  const states = overview?.services ?? {};
  const counts = overview?.counts ?? {};
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">THE NIGHT, IN GOOD HANDS</div>
          <h1>照看每一次相遇</h1>
          <p>从角色设定到一段记忆，星夜的运行细节都在这里。</p>
        </div>
        <Tag good={Object.values(states).every(Boolean) && !!overview}>
          {!overview
            ? "读取状态中"
            : Object.values(states).every(Boolean)
              ? "服务连接正常"
              : "部分服务需要检查"}
        </Tag>
      </div>
      <section className="service-map">
        <div className="map-caption">
          <span>服务星图</span>
          <small>LIVE CONNECTIONS</small>
        </div>
        <svg
          className="map-lines"
          viewBox="0 0 800 130"
          preserveAspectRatio="none"
          aria-hidden="true"
        >
          <path
            d="M110 65 C220 65 210 20 330 20 S455 65 530 65 S650 110 710 110 M330 20 C400 20 360 110 450 110 S640 65 710 110"
            stroke="currentColor"
            strokeWidth="1"
            fill="none"
            strokeDasharray="3 7"
          />
        </svg>
        <div className="service-nodes">
          {[
            ["admin", "管理入口", "8444 / HTTPS"],
            ["database", "账户与记忆", "POSTGRESQL"],
            ["ai", "角色推理", "AI WORKER"],
            ["redis", "会话与限流", "REDIS"],
          ].map(([key, title, note]) => (
            <div className="service-node" key={key}>
              <span className={"state-point " + (states[key] ? "ok" : "")} />
              <strong>{title}</strong>
              <small>{note}</small>
              <span>
                {overview ? (states[key] ? "已连接" : "待检查") : "读取中"}
              </span>
            </div>
          ))}
        </div>
      </section>
      <div className="dashboard-grid">
        <section className="panel catalog-panel">
          <div className="section-title">
            <h2>角色与内容</h2>
            <button
              className="text-button"
              onClick={() => choose("characters")}
            >
              管理目录
              <ArrowRight size={14} />
            </button>
          </div>
          <div className="catalog-total">
            <span>{counts.characters ?? "—"}</span>
            <div>
              个角色在目录中<small>资源发布与 AI 设定分别管理</small>
            </div>
            <Layers size={40} />
          </div>
          <div className="shortcut-grid">
            {[
              ["characters", "角色目录", "名称、介绍与可见性"],
              ["authors", "作者资料", "介绍与作品关联"],
              ["ai:profiles", "AI 角色设定", "人格、声音与场景"],
              ["character_releases", "资源发布", "清单与分发状态"],
            ].map(([id, title, desc]) => (
              <button
                key={id}
                onClick={() => choose(id)}
                disabled={
                  !resources.some((r) => (r.ai ? "ai:" : "") + r.id === id)
                }
              >
                <span>
                  {title}
                  <ArrowRight size={14} />
                </span>
                <small>{desc}</small>
              </button>
            ))}
          </div>
        </section>
        <section className="panel">
          <div className="section-title">
            <h2>相处的记录</h2>
            <MessageCircle size={18} />
          </div>
          {[
            ["users", "用户账户"],
            ["conversations", "角色会话"],
            ["messages", "已归档消息"],
            ["entries", "记忆与共同片段"],
            ["support_tickets", "反馈工单"],
          ].map(([id, name]) => (
            <button key={id} className="metric-row" onClick={() => choose(id)}>
              <span>{name}</span>
              <strong>{counts[id] ?? "—"}</strong>
              <ChevronRight size={15} />
            </button>
          ))}
          <p className="panel-note">
            归档消息与推理上下文分别保存，修改前请确认所需的数据范围。
          </p>
        </section>
      </div>
      <section className="panel admin-guide">
        <ShieldCheck size={22} />
        <div>
          <h3>每次修改，都能找到来处</h3>
          <p>
            版本校验保护并发编辑。重置会话、资源分发和服务重启需要再次确认，操作记录可随时查看。
          </p>
        </div>
        <button className="secondary" onClick={() => choose("admin_audit")}>
          查看操作记录
        </button>
      </section>
    </>
  );
}

function ResourceWorkspace({
  resource: r,
  user,
  refresh,
  ask,
  onChanged,
}: {
  resource: Resource;
  user: AdminUser;
  refresh: number;
  ask: (c: Confirmation) => void;
  onChanged: () => void;
}) {
  const [page, setPage] = useState<Page>({ items: [], next: "" }),
    [q, setQ] = useState(""),
    [query, setQuery] = useState(""),
    [cursors, setCursors] = useState<string[]>([""]),
    [loading, setLoading] = useState(false),
    [error, setError] = useState(""),
    [selected, setSelected] = useState<Row | null>(null),
    [create, setCreate] = useState(false);
  const seq = useRef(0);
  const cursor = cursors[cursors.length - 1];
  useEffect(() => {
    const id = setTimeout(() => {
      setQuery(q);
      setCursors([""]);
    }, 300);
    return () => clearTimeout(id);
  }, [q]);
  useEffect(() => {
    const generation = ++seq.current;
    setLoading(true);
    setError("");
    api<Page>(
      resourcePath(r) +
        "?q=" +
        encodeURIComponent(query) +
        "&after=" +
        encodeURIComponent(cursor),
    )
      .then((data) => {
        if (generation !== seq.current) return;
        setPage(data);
        setSelected((old) =>
          old
            ? (data.items.find(
                (row) =>
                  JSON.stringify(keysOf(r, row)) ===
                  JSON.stringify(keysOf(r, old)),
              ) ?? null)
            : null,
        );
      })
      .catch((e) => {
        if (generation === seq.current) setError(e.message);
      })
      .finally(() => {
        if (generation === seq.current) setLoading(false);
      });
  }, [r, query, cursor, refresh]);
  const canEdit =
    user.role !== "viewer" &&
    (!r.ai || user.role === "owner") &&
    (!["admin_users", "character_releases"].includes(r.id) ||
      user.role === "owner");
  const canCreate =
    user.role === "owner" &&
    !r.ai &&
    [
      "users",
      "admin_users",
      "characters",
      "authors",
      "subscriptions",
      "follows",
      "character_releases",
    ].includes(r.id);
  const preferred =
    r.id === "users"
      ? ["profile", "starry_id", "username", "guest"]
      : r.id === "characters"
        ? ["name", "id", "visibility", "version"]
        : r.id === "authors"
          ? ["data", "id", "user_id", "version"]
          : r.id === "profiles"
            ? ["name", "id", "version"]
            : r.id === "admin_audit"
              ? ["actor_name", "action", "resource", "outcome", "occurred_at"]
              : r.id === "messages"
                ? ["character_id", "role", "text", "created_at"]
                : r.id === "usage"
                  ? ["kind", "status", "units", "created"]
                  : r.fields
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
                      .slice(0, 4);
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">
            {r.ai ? "CHARACTER INTELLIGENCE" : "STARRY NIGHT / " + r.group}
          </div>
          <h1>{r.name}</h1>
          <p>{r.description}</p>
        </div>
        {canCreate && (
          <button className="primary" onClick={() => setCreate(true)}>
            <Plus size={16} />
            新建
          </button>
        )}
      </div>
      <div className={"data-layout " + (selected ? "has-detail" : "")}>
        <section className="panel table-panel">
          <div className="table-toolbar">
            <label className="search-box">
              <Search size={16} />
              <input
                aria-label="搜索当前分类"
                placeholder={"搜索" + r.name + "…"}
                value={q}
                onChange={(e) => setQ(e.target.value)}
              />
              {q && (
                <button aria-label="清除搜索" onClick={() => setQ("")}>
                  <X size={14} />
                </button>
              )}
            </label>
            <span>{loading ? "读取中…" : `${page.items.length} 条记录`}</span>
          </div>
          {error && <ErrorNote text={error} />}
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  {preferred.map((k, index) => (
                    <th
                      key={k}
                      className={
                        index === 0 &&
                        ["users", "characters", "profiles", "authors"].includes(
                          r.id,
                        )
                          ? "identity-column"
                          : ""
                      }
                    >
                      {labels[k] ?? k}
                    </th>
                  ))}
                  <th aria-label="查看详情" />
                </tr>
              </thead>
              <tbody>
                {page.items.map((row) => {
                  const key = JSON.stringify(keysOf(r, row));
                  const identity = recordIdentity(r, row);
                  return (
                    <tr
                      key={key}
                      className={
                        selected && JSON.stringify(keysOf(r, selected)) === key
                          ? "selected"
                          : ""
                      }
                      onClick={() => setSelected(row)}
                      tabIndex={0}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") setSelected(row);
                      }}
                      aria-label={
                        "查看 " +
                        compact(
                          row.name ?? row.starry_id ?? row.id ?? row._rowid,
                        )
                      }
                    >
                      {preferred.map((k, i) => (
                        <td key={k} className={i === 0 ? "primary-cell" : ""}>
                          {i === 0 && identity ? (
                            <div className="record-identity">
                              <RecordAvatar
                                identity={identity}
                                revision={`${row.version ?? row.updated_at ?? ""}:${refresh}`}
                              />
                              <span>
                                <strong>{identity.name}</strong>
                                <small>
                                  {compact(row[k]) !== identity.name
                                    ? compact(row[k])
                                    : identity.kind === "character"
                                      ? "角色"
                                      : identity.kind === "author"
                                        ? "作者"
                                        : "账户"}
                                </small>
                              </span>
                            </div>
                          ) : [
                              "character_id",
                              "user_id",
                              "author_id",
                              "owner_id",
                            ].includes(k) &&
                            typeof row[k] === "string" &&
                            row[k] ? (
                            <RecordReference
                              kind={
                                k === "character_id"
                                  ? "character"
                                  : k === "author_id"
                                    ? "author"
                                    : "user"
                              }
                              id={String(row[k])}
                              revision={refresh}
                            />
                          ) : [
                              "visibility",
                              "state",
                              "status",
                              "role",
                              "outcome",
                            ].includes(k) ? (
                            <Tag
                              good={[
                                "public",
                                "ok",
                                "completed",
                                "approved",
                                "owner",
                              ].includes(String(row[k]))}
                            >
                              {compact(row[k])}
                            </Tag>
                          ) : (
                            <span
                              className={
                                k.endsWith("id") || k === "version"
                                  ? "mono"
                                  : ""
                              }
                            >
                              {compact(row[k])}
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
            {!loading && page.items.length === 0 && (
              <Empty text="没有找到记录" />
            )}
          </div>
          <div className="pagination">
            <span>第 {cursors.length} 页 · 每页最多 50 条</span>
            <button
              className="icon-button"
              disabled={cursors.length === 1 || loading}
              aria-label="上一页"
              onClick={() => setCursors((xs) => xs.slice(0, -1))}
            >
              <ArrowLeft size={16} />
            </button>
            <button
              className="icon-button"
              disabled={!page.next || loading}
              aria-label="下一页"
              onClick={() => setCursors((xs) => [...xs, page.next])}
            >
              <ArrowRight size={16} />
            </button>
          </div>
        </section>
        {selected && (
          <div className="detail-holder">
            <Detail
              key={JSON.stringify(selected)}
              r={r}
              row={selected}
              refresh={refresh}
              canEdit={canEdit}
              ask={ask}
              onClose={() => setSelected(null)}
              onChanged={onChanged}
            />
          </div>
        )}
      </div>
      {selected && (
        <button
          className="detail-backdrop"
          aria-label="关闭详情"
          onClick={() => setSelected(null)}
        />
      )}
      <Dialog
        open={create}
        onClose={() => setCreate(false)}
        className="dialog-root"
      >
        <div className="dialog-shade" />
        <div className="dialog-position">
          <DialogPanel className="create-panel">
            <CreateForm
              resource={r}
              onClose={() => setCreate(false)}
              onChanged={onChanged}
            />
          </DialogPanel>
        </div>
      </Dialog>
    </>
  );
}
function JSONField({
  name,
  value,
  onChange,
}: {
  name: string;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const [text, setText] = useState(JSON.stringify(value ?? {}, null, 2)),
    [error, setError] = useState("");
  return (
    <label className="json-field">
      <span>
        {labels[name] ?? name}
        <small>JSON</small>
      </span>
      <textarea
        spellCheck={false}
        value={text}
        rows={Math.min(14, Math.max(5, text.split("\n").length))}
        onChange={(e) => {
          setText(e.target.value);
          try {
            const obj = JSON.parse(e.target.value);
            if (!obj || Array.isArray(obj) || typeof obj !== "object")
              throw new Error();
            setError("");
            onChange(obj);
          } catch {
            setError("请输入有效 JSON 对象");
            onChange(undefined);
          }
        }}
      />
      {error && <span className="field-error">{error}</span>}
    </label>
  );
}
function Detail({
  r,
  row,
  refresh,
  canEdit,
  ask,
  onClose,
  onChanged,
}: {
  r: Resource;
  row: Row;
  refresh: number;
  canEdit: boolean;
  ask: (c: Confirmation) => void;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [values, setValues] = useState<Row>(editableValues(r, row)),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [copied, setCopied] = useState(false);
  const keys = keysOf(r, row);
  const resetID = useRef(crypto.randomUUID());
  const mutate = async (action: string, password = "") => {
    await api(resourcePath(r) + "/mutate", {
      method: "POST",
      body: JSON.stringify({
        keys,
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
  };
  async function save() {
    setBusy(true);
    setError("");
    try {
      await mutate("edit");
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const name = compact(
    row.name ??
      (row.profile as Row)?.display_name ??
      (r.id === "authors" ? (row.data as Row)?.name : undefined) ??
      row.starry_id ??
      row.id ??
      row._rowid,
  );
  return (
    <section className="panel detail-panel">
      <div className="detail-top">
        <div className="eyebrow">记录详情</div>
        <button className="icon-button" onClick={onClose} aria-label="关闭详情">
          <X size={18} />
        </button>
      </div>
      <div className="detail-title">
        {recordIdentity(r, row) ? (
          <RecordAvatar
            className="detail-avatar"
            identity={recordIdentity(r, row)!}
            revision={`${row.version ?? row.updated_at ?? ""}:${refresh}`}
          />
        ) : (
          <span className="record-mark">{name.slice(0, 1)}</span>
        )}
        <div>
          <h2>{name}</h2>
          <small>{r.name}</small>
        </div>
      </div>
      <TabGroup>
        <TabList className="tabs">
          <Tab>概览</Tab>
          {!!r.edit?.length && canEdit && <Tab>编辑</Tab>}
          <Tab>原始数据</Tab>
        </TabList>
        <TabPanels>
          <TabPanel>
            <RecordGallery
              resource={r}
              row={row}
              revision={`${row.version ?? row.updated_at ?? ""}:${refresh}`}
            />
            <dl className="detail-facts">
              {r.fields
                .filter(
                  (k) =>
                    ![
                      "data",
                      "profile",
                      "manifest",
                      "capabilities",
                      "config",
                      "result",
                      "progress",
                    ].includes(k),
                )
                .map((k) => (
                  <div key={k}>
                    <dt>{labels[k] ?? k}</dt>
                    <dd>
                      {[
                        "character_id",
                        "user_id",
                        "author_id",
                        "owner_id",
                      ].includes(k) &&
                      typeof row[k] === "string" &&
                      row[k] ? (
                        <RecordReference
                          kind={
                            k === "character_id"
                              ? "character"
                              : k === "author_id"
                                ? "author"
                                : "user"
                          }
                          id={String(row[k])}
                          revision={refresh}
                        />
                      ) : typeof row[k] === "object" ? (
                        <pre>{JSON.stringify(row[k], null, 2)}</pre>
                      ) : (
                        compact(row[k])
                      )}
                    </dd>
                  </div>
                ))}
            </dl>
            {["profile", "data", "config", "progress", "manifest"]
              .filter((k) => row[k] && typeof row[k] === "object")
              .map((k) => (
                <div className="document-section" key={k}>
                  <h3>{labels[k] ?? k}</h3>
                  <ObjectSummary value={row[k] as Row} />
                </div>
              ))}
            {canEdit && !!r.actions?.length && (
              <div className="detail-actions">
                <h3>管理操作</h3>
                {r.actions.map((action) => (
                  <button
                    key={action}
                    className={
                      "action-row " +
                      (["reset", "remove", "archive"].includes(action)
                        ? "action-danger"
                        : "")
                    }
                    onClick={() =>
                      ask({
                        title: actionLabels[action] ?? action,
                        password: action === "reset_password",
                        danger: [
                          "reset",
                          "remove",
                          "archive",
                          "disable_release",
                        ].includes(action),
                        description:
                          action === "reset"
                            ? "清空此账户与角色的全部聊天记录、记忆和关系进度，并通知 AI 服务。此操作无法撤销。"
                            : action === "enable_release"
                              ? "确认已获得这份模型与相关资源的再分发权。启用后用户可以获取下载凭证。"
                              : action === "clear_unused"
                                ? "清理未使用的预生成回复。已发送消息的重播音频会保留。"
                                : action === "reset_password"
                                  ? "设置新密码后，该账户的旧会话将失效。"
                                  : `对“${name}”执行此操作。所有修改都会记入操作记录。`,
                        run: (password) => mutate(action, password),
                      })
                    }
                  >
                    {actionLabels[action] ?? action}
                    <ArrowRight size={14} />
                  </button>
                ))}
              </div>
            )}
            {r.ai && r.id === "profiles" && canEdit && (
              <button
                className="secondary voice-generate"
                onClick={() =>
                  ask({
                    title: "生成新音色",
                    description:
                      "此操作调用百炼付费音色模型。生成后先保存为候选音色，需要在音色任务中审核启用。",
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
                <Volume2 size={15} />
                生成候选音色
              </button>
            )}
          </TabPanel>
          {!!r.edit?.length && canEdit && (
            <TabPanel>
              <div className="edit-form">
                <p className="form-note">
                  仅修改下方字段。ID、内部版本和归属保持不变。
                </p>
                {r.edit.map((key) => {
                  const v = values[key];
                  return r.ai &&
                    ["profiles", "prompts", "config"].includes(r.id) &&
                    key === "data" ? (
                    <ObjectEditor
                      key={key}
                      value={v as Row}
                      onChange={(value) =>
                        setValues((old) => ({ ...old, [key]: value }))
                      }
                    />
                  ) : typeof row[key] === "object" ? (
                    <JSONField
                      key={key}
                      name={key}
                      value={v}
                      onChange={(value) =>
                        setValues((old) => ({ ...old, [key]: value }))
                      }
                    />
                  ) : typeof row[key] === "boolean" ? (
                    <label className="toggle-field" key={key}>
                      {labels[key] ?? key}
                      <input
                        type="checkbox"
                        checked={!!v}
                        onChange={(e) =>
                          setValues((old) => ({
                            ...old,
                            [key]: e.target.checked,
                          }))
                        }
                      />
                    </label>
                  ) : (
                    <label key={key}>
                      {labels[key] ?? key}
                      {["description", "text", "content"].includes(key) ? (
                        <textarea
                          rows={4}
                          value={String(v ?? "")}
                          onChange={(e) =>
                            setValues((old) => ({
                              ...old,
                              [key]: e.target.value,
                            }))
                          }
                        />
                      ) : (
                        <input
                          value={String(v ?? "")}
                          type={
                            typeof row[key] === "number" ? "number" : "text"
                          }
                          onChange={(e) =>
                            setValues((old) => ({
                              ...old,
                              [key]:
                                typeof row[key] === "number"
                                  ? Number(e.target.value)
                                  : e.target.value,
                            }))
                          }
                        />
                      )}
                    </label>
                  );
                })}
                {r.id === "users" && (
                  <label>
                    更换头像（JPEG / PNG，最多 512 KB）
                    <input
                      type="file"
                      accept="image/jpeg,image/png"
                      onChange={async (e) => {
                        const file = e.target.files?.[0];
                        if (!file) return;
                        if (file.size > 512 * 1024) {
                          setError("头像文件不能超过 512 KB");
                          return;
                        }
                        setBusy(true);
                        setError("");
                        try {
                          await api(
                            "/users/" +
                              row.id +
                              "/avatar?expected_version=" +
                              row.version,
                            {
                              method: "POST",
                              body: file,
                              headers: { "Content-Type": file.type },
                            },
                          );
                          onChanged();
                        } catch (error) {
                          setError((error as Error).message);
                        } finally {
                          setBusy(false);
                        }
                      }}
                    />
                  </label>
                )}
                {error && <ErrorNote text={error} />}
                <button
                  className="primary"
                  onClick={save}
                  disabled={
                    busy || Object.values(values).some((v) => v === undefined)
                  }
                >
                  <Check size={15} />
                  {busy ? "保存中…" : "保存修改"}
                </button>
              </div>
            </TabPanel>
          )}
          <TabPanel>
            <div className="raw-toolbar">
              <span>完整记录 · 受限字段已隐藏</span>
              <button
                className="icon-button"
                aria-label="复制记录"
                onClick={async () => {
                  try {
                    await navigator.clipboard.writeText(
                      JSON.stringify(row, null, 2),
                    );
                    setCopied(true);
                  } catch {
                    setError("复制失败，请手动选择内容");
                  }
                }}
              >
                {copied ? <Check size={15} /> : <Copy size={15} />}
              </button>
            </div>
            <pre className="raw-json">{JSON.stringify(row, null, 2)}</pre>
          </TabPanel>
        </TabPanels>
      </TabGroup>
    </section>
  );
}
function ObjectEditor({
  value,
  onChange,
}: {
  value: Row;
  onChange: (value: Row | undefined) => void;
}) {
  const locked = [
    "age",
    "age_policy",
    "age_boundary",
    "adult",
    "romance_allowed",
    "visual_age",
  ];
  const [draft, setDraft] = useState<Row>(value),
    [invalid, setInvalid] = useState<Set<string>>(new Set());
  const update = (key: string, v: unknown) => {
    const next = v === undefined ? draft : { ...draft, [key]: v };
    setDraft(next);
    const errors = new Set(invalid);
    if (v === undefined) errors.add(key);
    else errors.delete(key);
    setInvalid(errors);
    onChange(errors.size ? undefined : next);
  };
  return (
    <div className="object-editor">
      {Object.entries(draft)
        .sort(([a], [b]) => {
          const order = [
            "name",
            "occupation",
            "world",
            "dialogue_language",
            "background",
            "personality",
            "speaking_style",
            "scene",
            "secrets",
            "voice_prompt",
            "voice_delivery",
            "preview_text",
            "CORE_PLANNER",
            "PLANNER",
            "NARRATOR",
            "PERFORMER",
            "REPLY_LENGTH",
            "character_model",
            "suggestions_model",
            "translation_model",
            "tts_model",
            "asr_model",
            "paid_enabled",
          ];
          const rank = (key: string) =>
            order.includes(key) ? order.indexOf(key) : 100;
          return rank(a) - rank(b) || a.localeCompare(b);
        })
        .map(([key, v]) =>
          locked.includes(key) ? (
            <div className="locked-field" key={key}>
              <span>{labels[key] ?? key}</span>
              <small>{compact(v)} · 固定元数据</small>
            </div>
          ) : Array.isArray(v) ? (
            <label key={key}>
              {labels[key] ?? key}
              <textarea
                className="mono"
                rows={4}
                defaultValue={JSON.stringify(v, null, 2)}
                onChange={(e) => {
                  try {
                    const list = JSON.parse(e.target.value);
                    if (!Array.isArray(list)) throw Error();
                    update(key, list);
                  } catch {
                    update(key, undefined);
                  }
                }}
              />
              {invalid.has(key) && (
                <small className="field-error">请输入 JSON 数组</small>
              )}
            </label>
          ) : typeof v === "object" ? (
            <JSONField
              key={key}
              name={key}
              value={v}
              onChange={(next) => update(key, next)}
            />
          ) : typeof v === "boolean" ? (
            <label key={key} className="toggle-field">
              {labels[key] ?? key}
              <input
                type="checkbox"
                checked={v}
                onChange={(e) => update(key, e.target.checked)}
              />
            </label>
          ) : (
            <label key={key}>
              {labels[key] ?? key}
              {typeof v === "number" ? (
                <input
                  type="number"
                  value={String(v)}
                  onChange={(e) => update(key, Number(e.target.value))}
                />
              ) : (
                <textarea
                  rows={
                    String(v ?? "").length > 250
                      ? 8
                      : String(v ?? "").length > 80
                        ? 4
                        : 2
                  }
                  value={String(v ?? "")}
                  onChange={(e) => update(key, e.target.value)}
                />
              )}
            </label>
          ),
        )}
    </div>
  );
}
function ObjectSummary({ value }: { value: Row }) {
  return (
    <dl className="object-summary">
      {Object.entries(value).map(([k, v]) => (
        <div key={k}>
          <dt>{labels[k] ?? k}</dt>
          <dd>
            {typeof v === "object" ? (
              <details>
                <summary>{compact(v).slice(0, 100)}</summary>
                <pre>{JSON.stringify(v, null, 2)}</pre>
              </details>
            ) : (
              compact(v)
            )}
          </dd>
        </div>
      ))}
    </dl>
  );
}
const defaults: Record<string, Row> = {
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
};
function CreateForm({
  resource: r,
  onClose,
  onChanged,
}: {
  resource: Resource;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [values, setValues] = useState<Row>(defaults[r.id] ?? {}),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api("/create/" + r.id, {
        method: "POST",
        body: JSON.stringify(values),
      });
      onChanged();
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="detail-top">
        <div className="eyebrow">新建记录</div>
        <button className="icon-button" aria-label="关闭" onClick={onClose}>
          <X size={18} />
        </button>
      </div>
      <DialogTitle as="h2">新建{r.name}</DialogTitle>
      <form onSubmit={save} className="edit-form">
        {Object.entries(values).map(([key, v]) =>
          typeof v === "object" ? (
            <JSONField
              key={key}
              name={key}
              value={v}
              onChange={(value) =>
                setValues((old) => ({ ...old, [key]: value }))
              }
            />
          ) : typeof v === "boolean" ? (
            <label className="toggle-field" key={key}>
              {labels[key] ?? key}
              <input
                type="checkbox"
                checked={v}
                onChange={(e) =>
                  setValues((old) => ({ ...old, [key]: e.target.checked }))
                }
              />
            </label>
          ) : (
            <label key={key}>
              {labels[key] ?? key}
              <input
                value={String(v)}
                type={key === "password" ? "password" : "text"}
                autoComplete={key === "password" ? "new-password" : "off"}
                onChange={(e) =>
                  setValues((old) => ({ ...old, [key]: e.target.value }))
                }
              />
            </label>
          ),
        )}
        {error && <ErrorNote text={error} />}
        <button
          className="primary"
          disabled={busy || Object.values(values).some((v) => v === undefined)}
        >
          {busy ? "正在创建…" : "创建记录"}
          <Plus size={15} />
        </button>
      </form>
    </>
  );
}

function Operations({
  user,
  refresh,
  ask,
}: {
  user: AdminUser;
  refresh: number;
  ask: (c: Confirmation) => void;
}) {
  const [data, setData] = useState<{
      available: boolean;
      units: Service[];
      logs: string[];
    } | null>(null),
    [unit, setUnit] = useState("starry-api"),
    [error, setError] = useState(""),
    [ai, setAI] = useState<Row | null>(null);
  useEffect(() => {
    if (user.role !== "owner") return;
    api<{ available: boolean; units: Service[]; logs: string[] }>(
      "/operations?logs=" + unit,
    )
      .then(setData)
      .catch((e) => setError(e.message));
    api<Row>("/ai/console/overview")
      .then(setAI)
      .catch(() => {});
  }, [user, refresh, unit]);
  if (user.role !== "owner") return <Empty text="服务操作仅对所有者开放" />;
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">SERVICE OBSERVATORY</div>
          <h1>服务运行</h1>
          <p>查看进程、推理用量与日志。重启可能中断正在进行的对话。</p>
        </div>
      </div>
      {error && <ErrorNote text={error} />}
      <div className="operations-grid">
        {data?.units.map((service) => (
          <section className="panel service-card" key={service.id}>
            <div className="section-title">
              <h2>{service.id}</h2>
              <Tag good={service.ActiveState === "active"}>
                {service.ActiveState ?? "未知"}
              </Tag>
            </div>
            <dl>
              <div>
                <dt>进程</dt>
                <dd>{service.MainPID ?? "—"}</dd>
              </div>
              <div>
                <dt>内存</dt>
                <dd>
                  {service.MemoryCurrent &&
                  Number.isFinite(Number(service.MemoryCurrent))
                    ? (Number(service.MemoryCurrent) / 1048576).toFixed(1) +
                      " MB"
                    : "—"}
                </dd>
              </div>
            </dl>
            {["starry-api", "starry-ai"].includes(service.id) && (
              <button
                className="secondary"
                onClick={() =>
                  ask({
                    title: "重启 " + service.id,
                    description:
                      "正在进行的请求可能中断。重启不删除数据、缓存或账号。",
                    run: async () => {
                      await api("/operations/" + service.id + "/restart", {
                        method: "POST",
                        body: '{"confirmed":true}',
                      });
                    },
                  })
                }
              >
                <RefreshCw size={14} />
                重启服务
              </button>
            )}
          </section>
        ))}
      </div>
      {data && !data.available && (
        <ErrorNote text="当前环境未启用 systemd 服务操作；数据管理仍可使用。" />
      )}
      {ai && (
        <section className="panel runtime-summary">
          <h2>AI 服务与持久化音频</h2>
          <div>
            <span>
              音频缓存<strong>{compact(ai.audio_files)} 份</strong>
            </span>
            <span>
              缓存空间
              <strong>
                {(Number(ai.audio_bytes ?? 0) / 1048576).toFixed(1)} MB
              </strong>
            </span>
            <span>
              付费调用<strong>{ai.paid_enabled ? "已启用" : "已关闭"}</strong>
            </span>
            <span>
              完整 AI 角色<strong>{compact(ai.profiles)}</strong>
            </span>
          </div>
          <p className="panel-note">
            完整调用记录、预缓存状态和模型配置可在左侧 AI 分类中查看。
          </p>
        </section>
      )}
      <section className="panel logs-panel">
        <div className="section-title">
          <h2>近期日志</h2>
          <Menu>
            <MenuButton className="secondary">
              {unit}
              <ArrowDown size={13} />
            </MenuButton>
            <MenuItems anchor="bottom end" className="dropdown">
              {data?.units.map((s) => (
                <MenuItem key={s.id}>
                  <button onClick={() => setUnit(s.id)}>{s.id}</button>
                </MenuItem>
              ))}
            </MenuItems>
          </Menu>
        </div>
        <pre>{data?.logs.join("\n") || "暂无日志"}</pre>
      </section>
    </>
  );
}
