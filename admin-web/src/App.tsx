import { useEffect, useState } from "react";
import { Dialog, DialogPanel, DialogTitle } from "@headlessui/react";
import {
  ArrowLeft,
  ChevronRight,
  Database,
  Layers,
  LogOut,
  Menu,
  MoonStar,
  RefreshCw,
  Shield,
  Users,
  X,
} from "lucide-react";
import { api, setCSRF, type AdminUser, type Resource, type Row } from "./api";
import { BackendIndex, EntityExplorer } from "./EntityExplorer";
import {
  canEditResource,
  DataWorkspace,
  RecordDrawer,
  type Scope,
} from "./DataWorkspace";
import { Heading, Panel, scalar, State, Stats, useData } from "./ConsoleUI";
import { Management, tools, type Ask } from "./Management";
import { VoiceTimings } from "./VoiceTimings";
type Confirmation = Parameters<Ask>[0];
function route() {
  try {
    return decodeURIComponent(location.hash.slice(1)) || "directory:users";
  } catch {
    return "directory:users";
  }
}
function Login({ onLogin }: { onLogin: (user: AdminUser) => void }) {
  const [username, setUsername] = useState("owner"),
    [password, setPassword] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  return (
    <main className="login-shell">
      <div className="login-card">
        <div className="login-brand">
          <span className="brand-mark">
            <MoonStar size={22} />
          </span>
          <strong>星夜控制台</strong>
        </div>
        <h1>管理员登录</h1>
        <p>管理用户、角色与服务端数据。</p>
        <form
          className="edit-form"
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            setError("");
            try {
              const r = await api<{ user: AdminUser; csrf: string }>("/login", {
                method: "POST",
                body: JSON.stringify({ username, password }),
              });
              setCSRF(r.csrf);
              onLogin(r.user);
            } catch (err) {
              setError((err as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <label>
            账号
            <input
              name="username"
              autoComplete="username"
              required
              maxLength={32}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
          </label>
          <label>
            密码
            <input
              name="password"
              type="password"
              autoComplete="current-password"
              required
              maxLength={128}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          <State error={error} />
          <button className="primary" disabled={busy}>
            {busy ? "正在验证…" : "登录控制台"}
          </button>
        </form>
        <span className="login-foot">
          <Shield size={14} />
          独立管理权限 · 操作审计
        </span>
      </div>
    </main>
  );
}
export default function App() {
  const [user, setUser] = useState<AdminUser | null>(null),
    [checking, setChecking] = useState(true),
    [resources, setResources] = useState<Resource[]>([]),
    [view, setView] = useState(route),
    [nav, setNav] = useState(false),
    [refresh, setRefresh] = useState(0),
    [error, setError] = useState(""),
    [toast, setToast] = useState(""),
    [confirm, setConfirm] = useState<Confirmation | null>(null),
    [password, setPassword] = useState(""),
    [busy, setBusy] = useState(false),
    [actionError, setActionError] = useState(""),
    [edit, setEdit] = useState<{ r: Resource; row: Row } | null>(null);
  useEffect(() => {
    const expired = () => {
      setCSRF("");
      setUser(null);
    };
    window.addEventListener("admin-session-expired", expired);
    api<{ user: AdminUser; csrf: string }>("/session")
      .then((r) => {
        setCSRF(r.csrf);
        setUser(r.user);
      })
      .catch(() => {})
      .finally(() => setChecking(false));
    return () => window.removeEventListener("admin-session-expired", expired);
  }, []);
  useEffect(() => {
    if (!user) return;
    const c = new AbortController();
    Promise.allSettled([
      api<Resource[]>("/resources", { signal: c.signal }),
      api<Resource[]>("/ai/console/resources", { signal: c.signal }),
    ]).then(([base, ai]) => {
      if (c.signal.aborted) return;
      if (base.status === "rejected") {
        setError(base.reason.message);
        return;
      }
      setResources(
        base.value.concat(
          ai.status === "fulfilled"
            ? ai.value.map((r) => ({ ...r, ai: true }))
            : [],
        ),
      );
      if (ai.status === "rejected")
        setError("AI 数据暂不可用，用户和角色管理仍可使用。");
    });
    return () => c.abort();
  }, [user, refresh]);
  useEffect(() => {
    const change = () => {
      setView(route());
      setNav(false);
      setEdit(null);
      setError("");
      window.scrollTo({ top: 0 });
    };
    window.addEventListener("hashchange", change);
    return () => window.removeEventListener("hashchange", change);
  }, []);
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(""), 3500);
    return () => clearTimeout(t);
  }, [toast]);
  const navigate = (v: string) => {
    if (v === view) {
      setNav(false);
      return;
    }
    location.hash = encodeURIComponent(v);
  };
  const changed = () => {
    setRefresh((n) => n + 1);
    setToast("已完成，最新数据已刷新");
  };
  const ask: Ask = (c) => {
    setPassword("");
    setActionError("");
    setConfirm(c);
  };
  if (checking)
    return (
      <div className="session-check">
        <MoonStar size={26} />
        <span>正在连接控制台…</span>
      </div>
    );
  if (!user) return <Login onLogin={setUser} />;
  const userDim = view === "directory:users" || view.startsWith("user:"),
    roleDim = view === "directory:characters" || view.startsWith("character:"),
    dimension = userDim ? "用户" : roleDim ? "角色" : "后台数据",
    resource = resources.find((r) => (r.ai ? "ai:" : "") + r.id === view);
  const title =
    resource?.name ||
    (view === "backend"
      ? "数据分类"
      : view === "overview"
        ? "总览"
        : view === "operations"
          ? "服务运行"
          : view === "voice-timings"
            ? "语音耗时"
            : view.startsWith("manage:")
              ? tools.find((t) => view === "manage:" + t.id)?.name
              : undefined);
  const renderResource = (r: Resource, scope: Scope) => (
    <DataWorkspace
      key={(r.ai ? "ai:" : "") + r.id + JSON.stringify(scope)}
      resource={r}
      scope={scope}
      user={user}
      refresh={refresh}
      ask={ask}
      changed={changed}
      navigate={navigate}
      embedded
    />
  );
  return (
    <div className="app-shell">
      <aside className={"sidebar " + (nav ? "is-open" : "")}>
        <a className="brand" href="#directory%3Ausers">
          <span className="brand-mark">
            <MoonStar size={22} />
          </span>
          <span>
            <strong>星夜</strong>
            <small>服务端控制台</small>
          </span>
        </a>
        <nav aria-label="管理导航">
          <button
            aria-label="用户维度"
            className={"nav-item " + (userDim ? "active" : "")}
            onClick={() => navigate("directory:users")}
          >
            <Users size={18} />
            用户
          </button>
          <button
            aria-label="角色维度"
            className={"nav-item " + (roleDim ? "active" : "")}
            onClick={() => navigate("directory:characters")}
          >
            <Layers size={18} />
            角色
          </button>
          <button
            aria-label="后台数据维度"
            className={"nav-item " + (!userDim && !roleDim ? "active" : "")}
            onClick={() => navigate("backend")}
          >
            <Database size={18} />
            后台数据
          </button>
          <div className="nav-divider" />
          <span className="nav-caption">常用工具</span>
          {[
            { id: "overview", name: "总览" },
            { id: "voice-timings", name: "语音耗时" },
            { id: "operations", name: "服务运行" },
            ...(user.role === "owner"
              ? [
                  { id: "manage:library", name: "资源与模型" },
                  { id: "manage:audio", name: "声音文件" },
                  { id: "admin_audit", name: "管理审计" },
                ]
              : []),
          ].map((t) => (
            <button
              key={t.id}
              className={"nav-resource " + (view === t.id ? "active" : "")}
              onClick={() => navigate(t.id)}
            >
              {t.name}
              <ChevronRight size={13} />
            </button>
          ))}
        </nav>
        <div className="operator">
          <span className="operator-avatar">
            {user.username.slice(0, 1).toUpperCase()}
          </span>
          <span>
            <strong>{user.username}</strong>
            <small>{scalar(user.role, "role")}</small>
          </span>
          <button
            className="icon-button"
            aria-label="退出登录"
            onClick={async () => {
              try {
                await api("/logout", { method: "POST" });
                setCSRF("");
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
      <div className="main-shell">
        <header className="topbar">
          <button
            className="icon-button mobile-menu"
            aria-label="打开导航"
            onClick={() => setNav(true)}
          >
            <Menu size={19} />
          </button>
          <div className="breadcrumb">
            <button
              onClick={() =>
                navigate(
                  userDim
                    ? "directory:users"
                    : roleDim
                      ? "directory:characters"
                      : "backend",
                )
              }
            >
              {dimension}
            </button>
            {title && (
              <>
                <ChevronRight size={13} />
                <span>{title}</span>
              </>
            )}
          </div>
          <button
            className="secondary refresh-button"
            onClick={() => setRefresh((n) => n + 1)}
          >
            <RefreshCw size={14} />
            刷新
          </button>
        </header>
        <main className="content" key={view}>
          <State error={error} />
          {userDim || roleDim ? (
            <EntityExplorer
              view={view}
              resources={resources}
              refresh={refresh}
              navigate={navigate}
              renderResource={renderResource}
              editEntity={(r, row) => setEdit({ r, row })}
            />
          ) : view === "backend" ? (
            <BackendIndex
              resources={resources}
              navigate={navigate}
              tools={user.role === "owner" ? tools : []}
            />
          ) : view === "overview" ? (
            <Overview refresh={refresh} navigate={navigate} />
          ) : view === "operations" ? (
            <Operations refresh={refresh} user={user} ask={ask} />
          ) : view === "voice-timings" ? (
            <VoiceTimings refresh={refresh} />
          ) : view.startsWith("manage:") && user.role === "owner" ? (
            <Management
              key={view}
              view={view.slice(7)}
              refresh={refresh}
              ask={ask}
            />
          ) : resource ? (
            <>
              <button className="back-link" onClick={() => navigate("backend")}>
                <ArrowLeft size={14} />
                数据分类
              </button>
              <DataWorkspace
                resource={resource}
                user={user}
                refresh={refresh}
                ask={ask}
                changed={changed}
                navigate={navigate}
              />
            </>
          ) : (
            <State
              loading={!resources.length}
              error={resources.length ? "找不到此页面，请从左侧导航选择。" : ""}
            />
          )}
        </main>
      </div>
      {toast && (
        <div className="toast" role="status">
          {toast}
        </div>
      )}
      {edit && (
        <RecordDrawer
          key={JSON.stringify(edit.row) + refresh}
          resource={edit.r}
          row={edit.row}
          user={user}
          ask={ask}
          changed={() => {
            changed();
            setEdit(null);
          }}
          refresh={refresh}
          navigate={navigate}
          close={() => setEdit(null)}
        />
      )}
      <Dialog
        open={!!confirm}
        onClose={() => {
          if (!busy) setConfirm(null);
        }}
        className="dialog-root"
      >
        <div className="dialog-shade" />
        <div className="dialog-position">
          <DialogPanel className="modal-panel confirmation-panel">
            <DialogTitle>{confirm?.title}</DialogTitle>
            <p>{confirm?.description}</p>
            {confirm?.password && (
              <label>
                新密码
                <input
                  type="password"
                  autoComplete="new-password"
                  minLength={10}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </label>
            )}
            <State error={actionError} />
            <div className="modal-actions">
              <button
                className="secondary"
                disabled={busy}
                onClick={() => setConfirm(null)}
              >
                取消
              </button>
              <button
                className={confirm?.danger ? "danger-button" : "primary"}
                disabled={busy || (!!confirm?.password && password.length < 10)}
                onClick={async () => {
                  if (!confirm) return;
                  setBusy(true);
                  try {
                    await confirm.run(password);
                    setConfirm(null);
                    changed();
                  } catch (e) {
                    setActionError((e as Error).message);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                {busy ? "处理中…" : "确认操作"}
              </button>
            </div>
          </DialogPanel>
        </div>
      </Dialog>
    </div>
  );
}
function Overview({
  refresh,
  navigate,
}: {
  refresh: number;
  navigate: (s: string) => void;
}) {
  const { data, error, loading } = useData<{
    counts: Record<string, number>;
    services: Record<string, boolean>;
    time: string;
  }>("/overview", refresh);
  return (
    <>
      <Heading
        title="服务与数据总览"
        description="按需读取当前数据量和服务连接状态。"
      />
      <State error={error} loading={loading} />
      {data && (
        <>
          <Panel title="服务连接">
            <div className="service-grid">
              {Object.entries(data.services).map(([k, v]) => (
                <div key={k}>
                  <span
                    className={"status-dot " + (v ? "healthy" : "unhealthy")}
                  />
                  <strong>{k}</strong>
                  <span>{v ? "连接正常" : "连接异常"}</span>
                </div>
              ))}
            </div>
          </Panel>
          <Panel title="数据记录">
            <div className="overview-counts">
              {Object.entries(data.counts).map(([k, v]) => (
                <button key={k} onClick={() => navigate(k)}>
                  <span>{k}</span>
                  <strong>{v.toLocaleString()}</strong>
                  <ChevronRight size={14} />
                </button>
              ))}
            </div>
          </Panel>
          <p className="muted">更新时间：{scalar(data.time, "updated_at")}</p>
        </>
      )}
    </>
  );
}
function Operations({
  refresh,
  user,
  ask,
}: {
  refresh: number;
  user: AdminUser;
  ask: Ask;
}) {
  const [unit, setUnit] = useState("starry-api");
  const { data, error, loading } = useData<{
    units: Row[];
    logs: string[];
    available: boolean;
  }>("/operations?logs=" + unit, refresh);
  return (
    <>
      <Heading
        title="服务运行"
        description="查看服务状态与日志；重启操作会记录审计。"
      />
      <State loading={loading} error={error} />
      {data && (
        <>
          {!data.available && (
            <p className="panel-note">
              当前环境未启用服务管理。生产服务器可查看状态和日志。
            </p>
          )}
          <div className="operation-services">
            {data.units?.map((r) => (
              <Panel key={String(r.id)} title={String(r.id)}>
                <FactsService row={r} />
                {user.role === "owner" &&
                  ["starry-api", "starry-ai"].includes(String(r.id)) && (
                    <button
                      className="secondary"
                      onClick={() =>
                        ask({
                          title: "重启 " + r.id,
                          description:
                            "重启期间相关请求可能短暂中断。确认继续？",
                          run: async () => {
                            await api("/operations/" + r.id + "/restart", {
                              method: "POST",
                              body: JSON.stringify({ confirmed: true }),
                            });
                          },
                        })
                      }
                    >
                      重启服务
                    </button>
                  )}
              </Panel>
            ))}
          </div>
          <Panel
            title="服务日志"
            action={
              <select
                aria-label="日志服务"
                value={unit}
                onChange={(e) => setUnit(e.target.value)}
              >
                {data.units?.map((r) => (
                  <option key={String(r.id)} value={String(r.id)}>
                    {String(r.id)}
                  </option>
                ))}
              </select>
            }
          >
            <pre className="log-output">
              {data.logs?.join("\n") || "选择服务查看日志。"}
            </pre>
          </Panel>
        </>
      )}
    </>
  );
}
function FactsService({ row }: { row: Row }) {
  return (
    <dl className="facts">
      {Object.entries(row)
        .filter(([k]) => k !== "id")
        .map(([k, v]) => (
          <div key={k}>
            <dt>
              {(
                {
                  ActiveState: "运行状态",
                  SubState: "子状态",
                  MemoryCurrent: "占用内存",
                  MainPID: "进程 ID",
                } as Record<string, string>
              )[k] || k}
            </dt>
            <dd>{scalar(v)}</dd>
          </div>
        ))}
    </dl>
  );
}
