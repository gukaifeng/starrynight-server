import { useEffect, useState, type ReactNode } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Search,
  X,
  ChevronDown,
  LoaderCircle,
} from "lucide-react";
import { api, type Page, type Row } from "./api";

export const object = (v: unknown): Row =>
  v && typeof v === "object" && !Array.isArray(v) ? (v as Row) : {};
export const text = (v: unknown) => (typeof v === "string" ? v : "");
export const number = (v: unknown) => Number(v ?? 0).toLocaleString();
export const userName = (r: Row) =>
  text(object(r.profile).display_name) ||
  text(r.starry_id) ||
  text(r.username) ||
  "访客";
export const labels: Record<string, string> = {
  id: "标识",
  runtime_id: "运行角色 ID",
  asset_delivery: "资源提供方式",
  schema_version: "结构版本",
  local_preview: "本地预览",
  user_id: "用户 UUID",
  character_id: "角色 ID",
  author_id: "作者 ID",
  owner_id: "所有者",
  owner: "上下文所有者",
  character: "角色",
  base_id: "来源角色",
  username: "登录账号",
  starry_id: "星夜号",
  profile: "个人资料",
  data: "详细内容",
  name: "名称",
  description: "简介",
  visibility: "可见性",
  version: "版本",
  created_at: "创建时间",
  updated_at: "更新时间",
  created: "创建时间",
  modified: "修改时间",
  role: "权限 / 发言者",
  disabled: "已停用",
  hidden: "已隐藏",
  pinned: "已置顶",
  text: "文字",
  content: "内容",
  config: "目标配置",
  state: "状态",
  status: "状态",
  importance: "记忆权重",
  distributable: "允许分发",
  platform: "平台",
  manifest: "资源清单",
  kind: "类型",
  progress: "关系进度",
  password: "新密码",
  display_name: "昵称",
  avatar: "头像",
  cover: "封面",
  bio: "个人简介",
  content_type: "文件类型",
  category: "分类",
  release_id: "发布 ID",
  capabilities: "角色能力",
  session_epoch: "会话版本",
  occurred_at: "操作时间",
  action: "操作",
  outcome: "结果",
  actor_name: "操作者",
  target: "目标",
  request_id: "请求 ID",
  _rowid: "记录序号",
  guest: "访客账号",
  sequence: "消息顺序",
  updated: "更新时间",
  subscribed: "已订阅",
  subscribed_at: "订阅时间",
  conversation: "对话状态",
  preference: "专属偏好",
  goal_config: "相处目标",
  goal_progress: "关系进度",
  messages: "消息数",
  user_messages: "用户消息",
  ai_messages: "AI 消息",
  subscriptions: "订阅角色",
  follows: "关注作者",
  created_characters: "创建角色",
  conversations: "对话数",
  chatters: "对话用户",
  settings: "全局设置",
  author: "作者资料",
  short_term: "本次目标",
  long_term: "长期目标",
  mode: "相处模式",
  initial_relation: "初始关系",
  task: "陪伴任务",
  paused: "已暂停",
  confirmed_couple: "已确认恋人关系",
  extensions: "扩展设置",
  bond: "关系指标",
  familiarity: "熟悉度",
  trust: "信任度",
  affection: "好感度",
  task_progress: "任务进度",
  milestones: "关系里程碑",
  nickname: "专属称呼",
  user_address: "用户称呼",
  default_user_address: "默认称呼",
  font_size: "对话字号",
  language: "语言",
  theme: "主题",
  appearance_facts: "外观事实",
  identity: "身份设定",
  values: "价值观",
  knowledge_boundary: "知识边界",
  forbidden_patterns: "表达禁区",
  relationship_style: "关系风格",
  hotwords: "识别热词",
  secrets: "私有设定",
  gender: "性别",
  age: "年龄",
  occupation: "职业",
  world: "世界背景",
  personality: "性格",
  background: "成长背景",
  speaking_style: "说话风格",
  scene: "当前场景",
  voice_prompt: "音色设计",
  voice_delivery: "声音演绎",
  preview_text: "试听文本",
  dialogue_language: "对话语言",
  scenarios: "情景模式",
  voice_revision: "音色版本",
  profile_revision: "设定版本",
  CORE_PLANNER: "核心语音规划",
  PLANNER: "完整对话规划",
  NARRATOR: "心理与动作描写",
  PERFORMER: "表情动作规划",
  REPLY_LENGTH: "回复长度规则",
  character_model: "对话模型",
  suggestions_model: "接话预测模型",
  translation_model: "翻译模型",
  tts_model: "语音合成模型",
  asr_model: "语音识别模型",
  paid_enabled: "允许付费调用",
  enforce_conversation_limits: "每日用量限制",
  reaction_pool_size: "每场景缓存数量",
  reaction_pool_ttl_seconds: "互动缓存有效期（秒）",
  entry_pool_ttl_seconds: "问候缓存有效期（秒）",
  confirmed_distribution_rights: "已确认资源再分发权",
  units: "用量",
  calls: "调用次数",
  requests: "推理请求",
  memories: "自动记忆",
  reaction_drafts: "场景预缓存",
  quick_reply_sets: "接话候选缓存",
  last_message_at: "最近消息时间",
  bytes: "文件大小",
  key: "对象路径",
  account_exists: "已关联正式账户",
  source: "数据来源",
  usage: "用量统计",
  branches: "关系分支",
  admin_token: "管理令牌",
  duration_ms: "耗时（毫秒）",
  trace_id: "追踪 ID",
  metadata: "扩展资料",
  revision: "修订号",
  model: "模型",
  is_default: "默认",
  reset_id: "重置 ID",
};
const enums: Record<string, string> = {
  public: "公开",
  private: "私有",
  owner: "所有者",
  editor: "编辑者",
  viewer: "查看者",
  user: "用户",
  assistant: "AI",
  system: "系统",
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
  study: "陪学习",
  english: "练习英语",
  listening: "倾听",
  planning: "规划",
  ok: "正常",
  completed: "已完成",
  approved: "已审核",
  pending: "待处理",
  failed: "失败",
  success: "成功",
};
export function scalar(v: unknown, key = ""): string {
  if (v === undefined || v === null || v === "") return "—";
  if (typeof v === "boolean") return v ? "是" : "否";
  if (typeof v === "object") {
    if (Array.isArray(v)) return `${v.length} 项`;
    const r = object(v);
    return (
      text(r.display_name || r.name || r.text || r.content || r.bio) ||
      `${Object.keys(r).length} 个字段`
    );
  }
  const s = String(v);
  if (
    (key.endsWith("_at") ||
      ["created", "updated", "modified", "occurred_at"].includes(key)) &&
    !Number.isNaN(new Date(typeof v === "number" ? v * 1000 : s).getTime())
  )
    return new Date(typeof v === "number" ? v * 1000 : s).toLocaleString(
      "zh-CN",
      { hour12: false },
    );
  return [
    "role",
    "visibility",
    "mode",
    "initial_relation",
    "long_term",
    "task",
    "state",
    "status",
    "outcome",
  ].includes(key)
    ? enums[s] || s
    : s;
}
export function useData<T>(path: string, refresh = 0) {
  const [data, setData] = useState<T | null>(null),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(true);
  useEffect(() => {
    const c = new AbortController();
    setData(null);
    setLoading(true);
    setError("");
    api<T>(path, { signal: c.signal })
      .then((v) => {
        if (!c.signal.aborted) setData(v);
      })
      .catch((e) => {
        if (!c.signal.aborted) setError(e.message);
      })
      .finally(() => {
        if (!c.signal.aborted) setLoading(false);
      });
    return () => c.abort();
  }, [path, refresh]);
  return { data, error, loading };
}
export function State({
  loading,
  error,
  empty = false,
}: {
  loading?: boolean;
  error?: string;
  empty?: boolean;
}) {
  if (error)
    return (
      <div className="error-note" role="alert">
        {error}
      </div>
    );
  if (loading)
    return (
      <div className="state" role="status">
        <LoaderCircle size={17} className="spin" />
        正在读取…
      </div>
    );
  return empty ? <div className="state">暂无记录</div> : null;
}
export function SearchBox({
  value,
  onChange,
  label,
  placeholder,
}: {
  value: string;
  onChange: (s: string) => void;
  label: string;
  placeholder?: string;
}) {
  return (
    <label className="search-box">
      <Search size={16} />
      <input
        aria-label={label}
        placeholder={placeholder || label}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
      {value && (
        <button
          type="button"
          aria-label="清除搜索"
          onClick={() => onChange("")}
        >
          <X size={14} />
        </button>
      )}
    </label>
  );
}
export function useSearch(value: string) {
  const [query, setQuery] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setQuery(value.trim()), 300);
    return () => clearTimeout(t);
  }, [value]);
  return query;
}
export function Pager({
  page,
  cursors,
  setCursors,
  loading,
}: {
  page: Page | null;
  cursors: string[];
  setCursors: (v: string[]) => void;
  loading?: boolean;
}) {
  return (
    <footer className="pagination">
      <span>
        第 {cursors.length} 页 · 本页 {page?.items.length ?? 0} 条
      </span>
      <button
        className="secondary"
        disabled={loading || cursors.length === 1}
        onClick={() => setCursors(cursors.slice(0, -1))}
      >
        <ArrowLeft size={14} />
        上一页
      </button>
      <button
        className="secondary"
        disabled={loading || !page?.next}
        onClick={() => setCursors([...cursors, page!.next])}
      >
        下一页
        <ArrowRight size={14} />
      </button>
    </footer>
  );
}
export function Panel({
  title,
  action,
  children,
  className = "",
}: {
  title?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={"panel " + className}>
      {title && (
        <header className="section-head">
          <h2>{title}</h2>
          {action}
        </header>
      )}
      {children}
    </section>
  );
}
export function Facts({ data, keys }: { data: Row; keys?: string[] }) {
  return (
    <dl className="facts">
      {(keys || Object.keys(data)).map((k) => (
        <div key={k}>
          <dt>{labels[k] || k}</dt>
          <dd>
            {typeof data[k] === "object" && data[k] !== null ? (
              <StructuredData value={data[k]} depth={1} />
            ) : (
              scalar(data[k], k)
            )}
          </dd>
        </div>
      ))}
    </dl>
  );
}
export function StructuredData({
  value,
  depth = 0,
}: {
  value: unknown;
  depth?: number;
}) {
  if (value === null || value === undefined)
    return <span className="muted empty-value">未设置</span>;
  if (typeof value !== "object")
    return <span className="long-text">{scalar(value)}</span>;
  const entries = Array.isArray(value)
    ? value.map((v, i) => [String(i + 1), v] as const)
    : Object.entries(value);
  if (!entries.length)
    return <span className="muted empty-value">暂无内容</span>;
  return (
    <dl className={"structured-data " + (depth ? "nested" : "")}>
      {entries.map(([k, v]) => {
        const nested = v !== null && typeof v === "object";
        return (
          <div key={k}>
            <dt>{Array.isArray(value) ? `第 ${k} 项` : labels[k] || k}</dt>
            <dd>
              {nested ? (
                <details
                  className="data-branch"
                  open={depth === 0 && Object.keys(object(v)).length < 6}
                >
                  <summary>
                    <ChevronDown size={13} />
                    {Array.isArray(v)
                      ? `${v.length} 项`
                      : `${Object.keys(object(v)).length} 个字段`}
                  </summary>
                  <StructuredData value={v} depth={depth + 1} />
                </details>
              ) : (
                <span className="long-text">
                  {v === null || v === undefined ? "未设置" : scalar(v, k)}
                </span>
              )}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}
export function RawData({ value }: { value: unknown }) {
  return (
    <details className="raw-data">
      <summary>查看完整原始数据</summary>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </details>
  );
}
export function Heading({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {action}
    </div>
  );
}
export function Stats({ items }: { items: [string, unknown][] }) {
  return (
    <div className="stats">
      {items.map(([name, v]) => (
        <div key={name}>
          <span>{name}</span>
          <strong>{number(v)}</strong>
        </div>
      ))}
    </div>
  );
}
export function Tabs({
  items,
  selected,
  onChange,
}: {
  items: [string, string][];
  selected: string;
  onChange: (s: string) => void;
}) {
  return (
    <div className="tabs" role="tablist">
      {items.map(([id, name]) => (
        <button
          key={id}
          role="tab"
          aria-selected={selected === id}
          tabIndex={selected === id ? 0 : -1}
          onKeyDown={(e) => {
            const index = items.findIndex(([key]) => key === id);
            const next =
              e.key === "ArrowRight"
                ? (index + 1) % items.length
                : e.key === "ArrowLeft"
                  ? (index + items.length - 1) % items.length
                  : e.key === "Home"
                    ? 0
                    : e.key === "End"
                      ? items.length - 1
                      : -1;
            if (next < 0) return;
            e.preventDefault();
            onChange(items[next][0]);
            const parent = e.currentTarget.parentElement;
            parent
              ?.querySelectorAll<HTMLButtonElement>("[role=tab]")
              [next]?.focus();
          }}
          onClick={() => onChange(id)}
        >
          {name}
        </button>
      ))}
    </div>
  );
}
