import { useEffect, useState } from "react";
import { api } from "./api";
import { RefreshCw, Download } from "lucide-react";
type Span = {
  name: string;
  start_ms: number;
  duration_ms: number;
  beat_id?: string;
  bytes?: number;
  model?: string;
  audio_duration_ms?: number;
};
type Trace = {
  trace_id: string;
  kind: string;
  character: string;
  created: number;
  status: string;
  total_ms: number;
  gateway: Record<string, number>;
  marks: Record<string, number>;
  flags: Record<string, unknown>;
  spans: Span[];
  dropped_spans: number;
};
type Row = { id: string; character: string; kind: string; data: Trace };
const names: Record<string, string> = {
  "context.load": "加载上下文",
  "preparation.claim": "检查预缓存",
  "preparation.priority_queue": "后台预生成排队",
  "preparation.yield_to_foreground": "等待后台任务让出资源",
  "preparation.inflight_text_wait": "等待预生成文字",
  "preparation.inflight_audio_wait": "等待预生成语音",
  "plan.quality_review": "语言与去重检查",
  "reply.commit": "保存对话与关系",
  "tts.generate": "语音模型生成",
  "audio.cache_read": "读取语音缓存",
  "audio.cache_lookup": "检查语音缓存",
  "audio.cache_write_and_trim": "保存与整理语音缓存",
  "audio.ordered_queue_wait": "音频分段顺序排队",
  "audio.base64_encode": "音频分段编码",
  "tts.event_decode": "解析语音事件",
  "tts.pcm_decode": "解码模型音频",
  "stream.backpressure": "事件交付队列等待",
};
function title(name: string) {
  if (names[name]) return names[name];
  const purpose = name.includes(".suggestions")
    ? "接话预测"
    : name.includes(".performance")
      ? "表演规划"
      : name.includes(".tts")
        ? "语音模型"
        : "对话模型";
  if (name.startsWith("model.")) {
    if (name.endsWith(".http")) return purpose + "请求（含网络与推理）";
    if (name.endsWith(".json_decode")) return purpose + " JSON 解码";
    if (name.endsWith(".schema_validate")) return purpose + "结构校验";
    return "结构化模型调用总时长";
  }
  const phases: Record<string, string> = {
    connect_tcp: "TCP / DNS 连接",
    start_tls: "TLS 握手",
    send_request_headers: "发送请求头",
    send_request_body: "发送请求体",
    receive_response_headers: "等待响应头",
    receive_response_body: "接收响应",
    dispatch_to_transport: "请求分派至传输层",
    response_closed: "关闭响应流",
  };
  for (const [suffix, label] of Object.entries(phases))
    if (name.endsWith(suffix)) return purpose + " · " + label;
  return name;
}
function time(ms: number | undefined) {
  return ms === undefined
    ? "未发生"
    : ms < 1000
      ? `${ms.toFixed(1)} ms`
      : `${(ms / 1000).toFixed(3)} s`;
}
export function VoiceTimings({ refresh }: { refresh: number }) {
  const [items, setItems] = useState<Row[]>([]),
    [next, setNext] = useState(""),
    [selected, setSelected] = useState<Row | null>(null),
    [query, setQuery] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [all, setAll] = useState(false);
  async function load(after = "") {
    setBusy(true);
    setError("");
    try {
      const page = await api<{ items: Row[]; next: string }>(
        "/ai/console/resources/voice_traces?q=" +
          encodeURIComponent(query) +
          "&after=" +
          encodeURIComponent(after),
      );
      setItems((old) => (after ? [...old, ...page.items] : page.items));
      setNext(page.next);
    } catch (e) {
      setError(e instanceof Error ? e.message : "读取记录失败");
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    void load();
  }, [refresh]);
  const trace = selected?.data,
    spans =
      trace?.spans.filter(
        (s) =>
          all ||
          s.duration_ms >= 1 ||
          [
            "tts.generate",
            "audio.cache_read",
            "preparation.claim",
            "context.load",
            "reply.commit",
          ].includes(s.name),
      ) ?? [];
  const extent = Math.max(
    1,
    trace?.total_ms ?? 0,
    ...spans.map((s) => s.start_ms + s.duration_ms),
  );
  const longest = trace?.spans.reduce<Span | null>(
    (best, s) => (!best || s.duration_ms > best.duration_ms ? s : best),
    null,
  );
  function download() {
    if (!trace) return;
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(trace, null, 2)], { type: "application/json" }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = `voice-${trace.trace_id}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }
  return (
    <section className="voice-workspace">
      <div className="page-heading">
        <div>
          <div className="eyebrow">STARRY NIGHT / VOICE TIMELINE</div>
          <h1>语音耗时</h1>
          <p>
            逐次拆解生成、缓存与交付。用追踪 ID 对照手机日志；并行耗时不能相加。
          </p>
        </div>
        <button
          className="quiet-button"
          disabled={busy}
          onClick={() => void load()}
        >
          <RefreshCw size={16} />
          刷新
        </button>
      </div>
      {error && <div className="error-banner">{error}</div>}
      <div className="voice-trace-layout">
        <section className="panel voice-trace-list">
          <form
            className="voice-trace-search"
            onSubmit={(e) => {
              e.preventDefault();
              void load();
            }}
          >
            <input
              aria-label="搜索语音耗时"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="追踪 ID、角色或场景…"
            />
            <button className="quiet-button">查找</button>
          </form>
          {!items.length && !busy && (
            <p className="voice-empty">
              升级后产生的语音会显示在这里。旧记录没有分段埋点，不能补造历史耗时。
            </p>
          )}
          {items.map((row) => (
            <button
              key={row.id}
              className={
                "voice-trace-item " +
                (selected?.id === row.id ? "selected" : "")
              }
              onClick={() => {
                setSelected(row);
                setAll(false);
              }}
            >
              <span>
                {row.character}
                <small>
                  {row.kind} · {row.data.status}
                </small>
              </span>
              <span>
                {time(
                  row.data.marks.first_audio_egress ??
                    row.data.marks.first_audio_ready,
                )}
                <small>
                  首段音频 ·{" "}
                  {new Date(row.data.created * 1000).toLocaleString()}
                </small>
              </span>
            </button>
          ))}
          {next && (
            <button
              className="quiet-button"
              disabled={busy}
              onClick={() => void load(next)}
            >
              加载更多
            </button>
          )}
        </section>
        <section className="panel voice-trace-detail">
          {trace ? (
            <>
              <div className="voice-trace-detail-head">
                <div>
                  <div className="eyebrow">
                    {trace.kind} / {trace.status}
                  </div>
                  <h2>{trace.character}</h2>
                </div>
                <button className="quiet-button" onClick={download}>
                  <Download size={15} />
                  完整 JSON
                </button>
              </div>
              <label className="voice-trace-id">
                追踪 ID
                <input
                  readOnly
                  value={trace.trace_id}
                  onFocus={(e) => e.target.select()}
                />
              </label>
              <div className="voice-milestones">
                <div>
                  <small>文字准备好</small>
                  <strong>{time(trace.marks.text_ready)}</strong>
                </div>
                <div>
                  <small>首段音频交付</small>
                  <strong>
                    {time(
                      trace.marks.first_audio_egress ??
                        trace.marks.first_audio_ready,
                    )}
                  </strong>
                </div>
                <div>
                  <small>生产结束</small>
                  <strong>{time(trace.total_ms)}</strong>
                </div>
              </div>
              {longest && (
                <p className="voice-longest">
                  最长环节：<strong>{title(longest.name)}</strong> ·{" "}
                  {time(longest.duration_ms)}
                </p>
              )}
              <dl className="detail-facts">
                {Object.entries({ ...trace.gateway, ...trace.flags }).map(
                  ([key, value]) => (
                    <div className="voice-fact" key={key}>
                      <dt>{key}</dt>
                      <dd>{String(value)}</dd>
                    </div>
                  ),
                )}
              </dl>
              <p className="voice-explanation">
                横条重叠表示并行。生产结束不等于手机播放结束，音频长度单独标明。复用连接可能没有
                DNS/TLS 环节；模型内部排队与推理未公开，合并记在等待响应中。
              </p>
              <label className="voice-show-all">
                <input
                  type="checkbox"
                  checked={all}
                  onChange={(e) => setAll(e.target.checked)}
                />
                显示全部 {trace.spans.length} 个环节，包含每段音频处理
              </label>
              <div className="voice-waterfall">
                {spans.map((s, i) => (
                  <div className="voice-span" key={i}>
                    <div>
                      <span>{title(s.name)}</span>
                      <small>
                        {s.beat_id ?? s.model ?? ""}
                        {s.bytes !== undefined ? ` · ${s.bytes} B` : ""}
                        {s.audio_duration_ms !== undefined
                          ? ` · 音频长度 ${time(s.audio_duration_ms)}`
                          : ""}
                      </small>
                    </div>
                    <div className="voice-span-track">
                      <i
                        style={{
                          left: `${(s.start_ms / extent) * 100}%`,
                          width: `${Math.max(0.3, (s.duration_ms / extent) * 100)}%`,
                        }}
                      />
                    </div>
                    <span>
                      {time(s.duration_ms)}
                      <small>+{time(s.start_ms)}</small>
                    </span>
                  </div>
                ))}
              </div>
              {trace.dropped_spans > 0 && (
                <p>达到上限，另有 {trace.dropped_spans} 个細小环节未保留。</p>
              )}
            </>
          ) : (
            <p className="voice-empty">
              选择一条语音，查看生成、缓存和交付的时间轴。
            </p>
          )}
        </section>
      </div>
    </section>
  );
}
