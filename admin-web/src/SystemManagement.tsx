import { useEffect, useState } from "react";
import { api, compact, type Row } from "./api";
import {
  type Ask,
  bytes,
  Json,
  Message,
  Table,
  time,
  useData,
} from "./Management";

type Page = {
  items: Row[];
  next?: string;
  cursor?: string;
  complete?: boolean;
  maintenance?: boolean;
};
const esc = encodeURIComponent;
function JobStatus({ refresh }: { refresh: number }) {
  const [tick, setTick] = useState(0);
  const { data } = useData<Page>("/runtime/jobs", refresh + tick);
  const active =
    data?.items.filter((r) =>
      ["queued", "running"].includes(String(r.state)),
    ) ?? [];
  useEffect(() => {
    if (!active.length) return;
    const timer = setInterval(() => setTick((n) => n + 1), 2500);
    return () => clearInterval(timer);
  }, [active.length]);
  return active.length ? (
    <div className="maintenance-banner" role="status">
      {active.map((r) => (
        <p key={String(r.id)}>
          <span className="live-dot" />
          {compact(r.operation)} · {compact(r.stage ?? r.state)}
          <small>{String(r.id)}</small>
        </p>
      ))}
    </div>
  ) : null;
}
export function SystemManagement({
  view,
  refresh,
  ask,
  changed,
}: {
  view: string;
  refresh: number;
  ask: Ask;
  changed: () => void;
}) {
  return (
    <>
      <JobStatus refresh={refresh} />
      {view === "cache" ? (
        <Caches refresh={refresh} ask={ask} changed={changed} />
      ) : view === "config" ? (
        <Configuration refresh={refresh} ask={ask} changed={changed} />
      ) : view === "backups" ? (
        <Backups refresh={refresh} ask={ask} changed={changed} />
      ) : view === "releases" ? (
        <Releases refresh={refresh} ask={ask} changed={changed} />
      ) : view === "files" ? (
        <Files refresh={refresh} />
      ) : (
        <Jobs refresh={refresh} />
      )}
    </>
  );
}
function Caches({
  refresh,
  ask,
  changed,
}: {
  refresh: number;
  ask: Ask;
  changed: () => void;
}) {
  const [cursor, setCursor] = useState("0"),
    [history, setHistory] = useState<string[]>([]),
    [q, setQ] = useState(""),
    [selected, setSelected] = useState<Row | null>(null);
  const { data, error, loading } = useData<Page>(
    "/cache?cursor=" + cursor + "&q=" + esc(q),
    refresh,
  );
  const detail = useData<Row>(
    selected
      ? "/cache/detail?id=" + esc(String(selected.id))
      : "/cache?cursor=0",
    refresh,
  );
  return (
    <>
      <Message text={error} />
      <div className="management-toolbar">
        <input
          aria-label="搜索会话与缓存"
          value={q}
          placeholder="按名称搜索，不显示登录令牌"
          onChange={(e) => {
            setQ(e.target.value);
            setCursor("0");
            setHistory([]);
            setSelected(null);
          }}
        />
      </div>
      <p className="panel-note">
        会话只显示账户与过期时间。清理会话会让对应设备退出；清理限流缓存会重置该项计数。列表使用增量扫描，更新中的键可能重复出现。
      </p>
      <div className="management-split has-detail">
        <section className="panel management-list">
          {loading && <p>正在扫描…</p>}
          <Table
            rows={data?.items ?? []}
            onSelect={setSelected}
            selected={selected}
            columns={[
              ["key", "缓存"],
              ["type", "类型"],
              ["ttl_seconds", "剩余秒数"],
              ["bytes", "占用"],
            ]}
          />
          <div className="pagination">
            <button
              className="secondary"
              disabled={!history.length}
              onClick={() => {
                setCursor(history.at(-1) ?? "0");
                setHistory(history.slice(0, -1));
              }}
            >
              上一页
            </button>
            <button
              className="secondary"
              disabled={data?.complete !== false}
              onClick={() => {
                setHistory([...history, cursor]);
                setCursor(data?.cursor ?? "0");
                setSelected(null);
              }}
            >
              继续扫描
            </button>
          </div>
        </section>
        {selected && (
          <aside className="panel management-detail">
            <h2>{String(selected.key)}</h2>
            <Json data={selected} />
            <Message text={detail.error} />
            {detail.data && <Json data={detail.data} />}
            <button
              className="danger-button"
              disabled={!detail.data?.version}
              onClick={() =>
                ask({
                  title: selected.session ? "撤销该登录会话" : "清理该缓存",
                  danger: true,
                  description:
                    "只影响当前选中项。若内容在确认期间变化，服务器会拒绝清理。",
                  run: async () => {
                    await api("/cache/clear", {
                      method: "POST",
                      body: JSON.stringify({
                        id: selected.id,
                        version: detail.data?.version,
                        confirmed: true,
                      }),
                    });
                    setSelected(null);
                    changed();
                  },
                })
              }
            >
              {selected.session ? "撤销会话" : "清理缓存"}
            </button>
          </aside>
        )}
      </div>
    </>
  );
}
type ConfigData = {
  version: string;
  platform: Row;
  ai: Row;
  platform_edit: string[];
  ai_edit: string[];
  routing: string;
  note: string;
};
const fieldNames: Record<string, string> = {
  STARRY_ENV: "运行环境",
  DATABASE_URL: "数据库连接",
  REDIS_URL: "会话存储连接",
  DB_POOL_SIZE: "数据库连接池",
  ALLOW_TEST_GUEST: "测试游客登录",
  AI_SERVICE_TOKEN: "App 与 AI 服务凭据",
  OSS_REGION: "OSS 地域",
  OSS_BUCKET: "OSS 存储桶",
  OSS_ENDPOINT: "OSS 服务地址",
  OSS_CREDENTIAL_SOURCE: "OSS 凭据来源",
  OSS_ACCESS_KEY_ID: "OSS AccessKey ID",
  OSS_ACCESS_KEY_SECRET: "OSS AccessKey Secret",
  OSS_SESSION_TOKEN: "OSS 临时凭据",
  api_key: "百炼 API Key",
  client_token: "AI 客户端凭据",
  admin_token: "AI 管理凭据",
  host: "百炼服务地址",
  semantic_novelty: "语义去重",
};
function Configuration({
  refresh,
  ask,
  changed,
}: {
  refresh: number;
  ask: Ask;
  changed: () => void;
}) {
  const { data, error } = useData<ConfigData>("/runtime/config", refresh);
  const [platform, setPlatform] = useState<Row>({}),
    [ai, setAI] = useState<Row>({});
  useEffect(() => {
    setPlatform({});
    setAI({});
  }, [data?.version]);
  const fields = (group: "platform" | "ai") => {
    const current = data?.[group] ?? {},
      editable = new Set(
        data?.[group === "platform" ? "platform_edit" : "ai_edit"] ?? [],
      ),
      patch = group === "platform" ? platform : ai,
      set = group === "platform" ? setPlatform : setAI;
    const keys = [...new Set([...Object.keys(current), ...editable])];
    return (
      <div className="configuration-fields">
        {keys.map((key) => {
          const value = current[key];
          const secret =
            /password|token|api_key|secret|database_url|redis_url|access_key/i.test(
              key,
            ) ||
            (typeof value === "object" &&
              value !== null &&
              "configured" in value);
          const display = patch[key] ?? (secret ? "" : (value ?? ""));
          return (
            <label key={key}>
              {fieldNames[key] ?? key}
              <small>
                {key}
                {secret
                  ? (value as Row | undefined)?.configured
                    ? " · 已配置"
                    : " · 未配置"
                  : ""}
              </small>
              {typeof value === "boolean" ? (
                <select
                  aria-label={fieldNames[key] ?? key}
                  disabled={!editable.has(key)}
                  value={String(display)}
                  onChange={(e) =>
                    set({ ...patch, [key]: e.target.value === "true" })
                  }
                >
                  <option value="true">启用</option>
                  <option value="false">关闭</option>
                </select>
              ) : (
                <input
                  aria-label={fieldNames[key] ?? key}
                  type={secret ? "password" : "text"}
                  autoComplete={secret ? "new-password" : "off"}
                  disabled={!editable.has(key)}
                  placeholder={secret ? "留空保留，输入新值替换" : ""}
                  value={String(display)}
                  onChange={(e) => set({ ...patch, [key]: e.target.value })}
                />
              )}
            </label>
          );
        })}
      </div>
    );
  };
  return (
    <>
      <Message text={error} />
      {data && (
        <>
          <p className="panel-note">
            {data.note}{" "}
            凭据只允许替换，不返回原值。修改数据库连接前请确保目标数据已就绪。
          </p>
          <div className="configuration-grid">
            <section className="panel">
              <h2>账户与对象存储</h2>
              {fields("platform")}
            </section>
            <section className="panel">
              <h2>AI 服务与凭据</h2>
              {fields("ai")}
              <p className="panel-note">
                对话模型、声音模型、预算和预缓存参数在后台数据的“模型与预算”中管理。
              </p>
            </section>
          </div>
          <div className="management-toolbar">
            <button
              className="primary"
              onClick={() =>
                ask({
                  title: "保存运行配置",
                  description:
                    "先验证数据库与 Redis 连接，备份原配置，再保存。服务在点击应用前继续使用当前配置。",
                  run: async () => {
                    await api("/runtime/config", {
                      method: "POST",
                      body: JSON.stringify({
                        confirmed: true,
                        expected_version: data.version,
                        platform,
                        ai,
                      }),
                    });
                    changed();
                  },
                })
              }
            >
              验证并保存配置
            </button>
            <button
              className="secondary"
              onClick={() =>
                ask({
                  title: "应用已保存配置",
                  description:
                    "将重启 API、AI 和管理进程，正在进行的对话可能中断。应用结果在维护任务中显示。",
                  run: async () => {
                    await api("/runtime/config", {
                      method: "POST",
                      body: JSON.stringify({
                        confirmed: true,
                        operation: "apply",
                      }),
                    });
                    changed();
                  },
                })
              }
            >
              应用配置
            </button>
          </div>
          <details className="panel">
            <summary>入口路由（只读）</summary>
            <pre className="management-json">{data.routing}</pre>
          </details>
        </>
      )}
    </>
  );
}
function Backups({
  refresh,
  ask,
  changed,
}: {
  refresh: number;
  ask: Ask;
  changed: () => void;
}) {
  const { data, error } = useData<Page>("/runtime/backups", refresh);
  const [selected, setSelected] = useState<Row | null>(null),
    [confirmation, setConfirmation] = useState("");
  const operation = (op: string, id?: unknown) =>
    api("/runtime/backups", {
      method: "POST",
      body: JSON.stringify({
        confirmed: true,
        operation: op,
        id,
        confirmation,
      }),
    });
  return (
    <>
      <Message text={error} />
      <div className="management-toolbar">
        <p className="panel-note">
          完整备份包含账户数据库、AI
          状态、媒体与资源库。恢复保留当前入口和凭据、当前管理员与审计，并撤销旧登录。历史不完整备份可查看和下载。
        </p>
        <button
          className="primary"
          onClick={() =>
            ask({
              title: "创建完整备份",
              description:
                "API 和 AI 将短暂暂停，保证账户与推理数据处于同一备份边界。已有文件不会删除。",
              run: async () => {
                await operation("backup");
                changed();
              },
            })
          }
        >
          创建完整备份
        </button>
      </div>
      <div className="management-split has-detail">
        <section className="panel management-list">
          <Table
            rows={data?.items ?? []}
            onSelect={(r) => {
              setSelected(r);
              setConfirmation("");
            }}
            selected={selected}
            columns={[
              ["id", "备份"],
              ["created", "创建"],
              ["bytes", "大小"],
              ["restorable", "完整可恢复"],
            ]}
          />
        </section>
        {selected && (
          <aside className="panel management-detail">
            <h2>{String(selected.id)}</h2>
            <p>{bytes(selected.bytes)}</p>
            <Table
              rows={(selected.files as Row[]) ?? []}
              columns={[
                ["name", "文件"],
                ["bytes", "大小"],
              ]}
            />
            <div className="backup-downloads">
              {((selected.files as Row[]) ?? [])
                .filter((f) =>
                  [
                    "platform.dump",
                    "ai-state.sqlite3",
                    "media.tar.gz",
                    "control-room-manifest.json",
                    "redis.rdb",
                    "manifest.json",
                  ].includes(String(f.name)),
                )
                .map((f) => (
                  <a
                    className="secondary"
                    key={String(f.name)}
                    href={
                      "/admin-api/v1/runtime-download?kind=backup&id=" +
                      esc(String(selected.id)) +
                      "&file=" +
                      esc(String(f.name))
                    }
                    download
                  >
                    下载 {String(f.name)}
                  </a>
                ))}
            </div>
            {selected.quarantined ? (
              <button
                className="secondary"
                onClick={() =>
                  ask({
                    title: "恢复备份",
                    description: "移回可用备份目录。",
                    run: async () => {
                      await operation("recover", selected.id);
                      setSelected(null);
                      changed();
                    },
                  })
                }
              >
                恢复备份
              </button>
            ) : selected.restorable ? (
              <>
                <button
                  className="secondary"
                  onClick={() =>
                    ask({
                      title: "检查备份完整性",
                      description:
                        "核对全部文件的大小、校验码、数据库和归档安全性，不修改当前业务数据。",
                      run: async () => {
                        await operation("verify-backup", selected.id);
                        changed();
                      },
                    })
                  }
                >
                  验证备份
                </button>
                <label>
                  恢复确认
                  <input
                    aria-label="恢复确认"
                    placeholder="输入：恢复全部业务数据"
                    value={confirmation}
                    onChange={(e) => setConfirmation(e.target.value)}
                  />
                </label>
                <button
                  className="danger-button"
                  disabled={confirmation !== "恢复全部业务数据"}
                  onClick={() =>
                    ask({
                      title: "恢复全部业务数据",
                      danger: true,
                      description:
                        "会覆盖备份之后的业务变化。先创建保护备份、验证独立候选库，再切换；所有用户和管理员需要重新登录。",
                      run: async () => {
                        await operation("restore", selected.id);
                        changed();
                      },
                    })
                  }
                >
                  开始恢复
                </button>
              </>
            ) : (
              <p className="panel-note">
                这份历史备份尚未具备新版完整恢复清单；不将缺失内容当作完整备份恢复。
              </p>
            )}
            <button
              className="danger-button"
              disabled={!!selected.quarantined}
              onClick={() =>
                ask({
                  title: "移除备份",
                  danger: true,
                  description:
                    "从可用备份列表移入服务器回收目录。维护任务进行中不能移除备份。",
                  run: async () => {
                    await operation("delete", selected.id);
                    setSelected(null);
                    changed();
                  },
                })
              }
            >
              移除备份
            </button>
          </aside>
        )}
      </div>
    </>
  );
}
function Releases({
  refresh,
  ask,
  changed,
}: {
  refresh: number;
  ask: Ask;
  changed: () => void;
}) {
  const releases = useData<Page>("/runtime/releases", refresh),
    certs = useData<Page>("/runtime/certificates", refresh),
    services = useData<Row>("/operations", refresh);
  const [selected, setSelected] = useState<Row | null>(null);
  return (
    <>
      <Message text={releases.error || certs.error || services.error} />
      <div className="configuration-grid">
        <section className="panel">
          <h2>服务端版本</h2>
          <p className="panel-note">
            切换已构建的完整版本，执行迁移和就绪检查。代码回滚不逆向回滚数据库；恢复数据请使用备份页。
          </p>
          <Table
            rows={releases.data?.items ?? []}
            onSelect={setSelected}
            selected={selected}
            columns={[
              ["id", "版本"],
              ["commit", "提交"],
              ["current", "当前"],
            ]}
          />
          {selected && !selected.current && (
            <button
              className="primary"
              onClick={() =>
                ask({
                  title: "切换服务端版本",
                  description:
                    "将备份数据库并重启服务，正在进行的请求可能中断。失败时由部署工具恢复原代码入口。",
                  run: async () => {
                    await api("/runtime/releases", {
                      method: "POST",
                      body: JSON.stringify({
                        confirmed: true,
                        id: selected.id,
                      }),
                    });
                    changed();
                  },
                })
              }
            >
              应用所选版本
            </button>
          )}
        </section>
        <section className="panel">
          <h2>HTTPS 证书</h2>
          {certs.data?.items.map((r) => (
            <div key={String(r.name)}>
              <h3>{String(r.name)}</h3>
              <pre className="management-json">{String(r.information)}</pre>
            </div>
          ))}
          <button
            className="secondary"
            onClick={() =>
              ask({
                title: "检查并续期证书",
                description:
                  "执行服务器现有证书续期服务。仍在有效期内的证书不强制重新签发。",
                run: async () => {
                  await api("/runtime/certificates", {
                    method: "POST",
                    body: JSON.stringify({ confirmed: true }),
                  });
                  changed();
                },
              })
            }
          >
            检查续期
          </button>
        </section>
      </div>
      <section className="panel">
        <h2>服务维护</h2>
        <p className="panel-note">
          固定服务范围，不接受任意命令。重启数据库或入口会短暂影响全部连接。
        </p>
        <div className="service-actions">
          {[
            "starry-api",
            "starry-ai",
            "starry-admin",
            "starry-edge",
            "starry-postgres",
            "starry-redis",
          ].map((unit) => (
            <button
              className="secondary"
              key={unit}
              onClick={() =>
                ask({
                  title: "重启 " + unit,
                  danger: ["starry-postgres", "starry-redis"].includes(unit),
                  description: "服务将短暂中断，结果记录在维护任务中。",
                  run: async () => {
                    await api("/runtime/services", {
                      method: "POST",
                      body: JSON.stringify({ confirmed: true, unit }),
                    });
                    changed();
                  },
                })
              }
            >
              {unit}
            </button>
          ))}
        </div>
      </section>
    </>
  );
}
function Files({ refresh }: { refresh: number }) {
  const [folder, setFolder] = useState("release"),
    [q, setQ] = useState(""),
    [after, setAfter] = useState(""),
    [history, setHistory] = useState<string[]>([]);
  const { data, error } = useData<Page>(
    "/runtime/files?folder=" + folder + "&q=" + esc(q) + "&after=" + esc(after),
    refresh,
  );
  const connections = useData<Page>("/runtime/connections", refresh);
  return (
    <>
      <Message text={error || connections.error} />
      <section className="panel">
        <h2>连接拓扑</h2>
        <Table
          rows={connections.data?.items ?? []}
          columns={[
            ["name", "连接"],
            ["host", "主机"],
            ["port", "端口"],
            ["credentials_configured", "配置凭据"],
          ]}
        />
      </section>
      <div className="management-toolbar">
        <select
          aria-label="服务器目录"
          value={folder}
          onChange={(e) => {
            setFolder(e.target.value);
            setAfter("");
            setHistory([]);
          }}
        >
          {[
            ["release", "当前发布"],
            ["config", "私有配置"],
            ["backups", "备份"],
            ["library", "资源库"],
            ["admin", "维护记录"],
            ["ai", "AI 数据"],
          ].map(([id, name]) => (
            <option key={id} value={id}>
              {name}
            </option>
          ))}
        </select>
        <input
          aria-label="搜索服务器文件"
          placeholder="按文件路径搜索"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setAfter("");
            setHistory([]);
          }}
        />
      </div>
      <p className="panel-note">
        显示约定目录内的文件、大小、修改时间和权限。配置文件中的凭据保持隐藏；媒体内容在资源与声音页面查看。
      </p>
      <section className="panel">
        <Table
          rows={data?.items ?? []}
          columns={[
            ["name", "相对路径"],
            ["bytes", "大小"],
            ["modified", "修改时间"],
            ["permission", "权限"],
          ]}
        />
        <div className="pagination">
          <button
            className="secondary"
            disabled={!history.length}
            onClick={() => {
              setAfter(history.at(-1) ?? "");
              setHistory(history.slice(0, -1));
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
            }}
          >
            下一页
          </button>
        </div>
      </section>
    </>
  );
}
function Jobs({ refresh }: { refresh: number }) {
  const [tick, setTick] = useState(0),
    [selected, setSelected] = useState<Row | null>(null);
  const { data, error } = useData<Page>("/runtime/jobs", refresh + tick);
  useEffect(() => {
    if (
      !data?.items.some((r) => ["queued", "running"].includes(String(r.state)))
    )
      return;
    const timer = setInterval(() => setTick((n) => n + 1), 2500);
    return () => clearInterval(timer);
  }, [data]);
  const row = data?.items.find((r) => r.id === selected?.id) ?? selected;
  return (
    <>
      <Message text={error} />
      <p className="panel-note">
        维护任务独立于浏览器请求运行。刷新或退出页面不会中断任务；运行期间写入操作暂停，避免备份和恢复的数据边界变化。
      </p>
      <div className="management-split has-detail">
        <section className="panel">
          <Table
            rows={data?.items ?? []}
            onSelect={setSelected}
            selected={row}
            columns={[
              ["operation", "任务"],
              ["state", "状态"],
              ["stage", "进度"],
              ["created", "开始时间"],
            ]}
          />
        </section>
        {row && (
          <aside className="panel management-detail">
            <h2>{compact(row.operation)}</h2>
            <Json data={row} />
          </aside>
        )}
      </div>
    </>
  );
}
