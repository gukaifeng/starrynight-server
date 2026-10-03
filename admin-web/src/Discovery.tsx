import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { Dialog, DialogPanel, DialogTitle } from "@headlessui/react";
import { ArrowDownCircle, Search, X } from "lucide-react";
import { Heading, object, Panel, State, text, useData } from "./ConsoleUI";
import { bytes } from "./Management";
import {
  catalogueCategories,
  categoriesOf,
  coverFrame,
  descriptorOf,
  discoveryResults,
  displayOf,
  invitationOf,
  nameOf,
  profileOf,
  scenariosOf,
  strings,
  type DiscoveryItem,
  type DiscoveryReport,
  type HeadBounds,
} from "./DiscoveryContent";

function Cover({ item }: { item: DiscoveryItem }) {
  const box = useRef<HTMLDivElement>(null),
    image = useRef<HTMLImageElement>(null);
  const [style, setStyle] = useState<CSSProperties>({}),
    [failed, setFailed] = useState(false);
  const layout = object(item.data.cover_layout),
    head = object(layout.headBounds);
  const update = () => {
    const bounds = box.current,
      artwork = image.current;
    if (!bounds || !artwork) return;
    const frame = coverFrame(
      artwork.naturalWidth,
      artwork.naturalHeight,
      bounds.clientWidth,
      bounds.clientHeight,
      head as HeadBounds,
    );
    setStyle(frame ? { ...frame, position: "absolute", maxWidth: "none" } : {});
  };
  useEffect(() => {
    const observer = new ResizeObserver(update);
    if (box.current) observer.observe(box.current);
    return () => observer.disconnect();
  }, [item]);
  return (
    <div className="discover-cover" ref={box}>
      {item.media.cover && !failed ? (
        <img
          ref={image}
          src={item.media.cover.url}
          alt=""
          loading="lazy"
          style={style}
          onLoad={update}
          onError={() => setFailed(true)}
        />
      ) : (
        <span className="discover-cover-empty">封面暂不可用</span>
      )}
    </div>
  );
}

function CharacterDetails({
  item,
  categories,
  close,
  navigate,
}: {
  item: DiscoveryItem;
  categories: string[];
  close: () => void;
  navigate: (v: string) => void;
}) {
  const profile = profileOf(item),
    descriptor = descriptorOf(item),
    display = displayOf(item),
    collection = object(item.data.collection);
  const actions = Array.isArray(descriptor.actions)
    ? descriptor.actions
        .filter((a) => object(a).button === true)
        .map((a) => text(object(a).label))
    : [];
  const voices = Array.isArray(collection.voices)
    ? collection.voices.map((v) => object(v))
    : [];
  const music = Array.isArray(collection.music)
    ? collection.music.map((v) => object(v))
    : [];
  return (
    <Dialog open onClose={close} className="drawer-root">
      <div className="dialog-shade" />
      <div className="drawer-position">
        <DialogPanel className="drawer-panel discover-detail">
          <header className="drawer-head">
            <div>
              <DialogTitle>{nameOf(item)}</DialogTitle>
              <span className="muted">角色资料</span>
            </div>
            <button
              className="icon-button"
              aria-label="关闭角色资料"
              onClick={close}
            >
              <X size={18} />
            </button>
          </header>
          <div className="discover-detail-body">
            <Cover item={item} />
            <div className="discover-identity">
              {item.media.avatar && (
                <img src={item.media.avatar.url} alt="角色头像" />
              )}
              <div>
                <h3>{nameOf(item)}</h3>
                <p>{text(profile.occupation) || text(display.tagline)}</p>
              </div>
            </div>
            <div className="discover-tags">
              {categories.map((c) => (
                <span key={c}>{c}</span>
              ))}
              <span>
                {collection.previewOnly === true ? "模型预览" : "对话角色"}
              </span>
            </div>
            <p className="discover-invitation">{invitationOf(item)}</p>
            {!!strings(profile.traits).length && (
              <p className="discover-traits">
                {strings(profile.traits).join(" · ")}
              </p>
            )}
            <p className="discover-story">
              {text(profile.story) || item.description}
            </p>
            {!!strings(profile.likes).length && (
              <p>喜欢：{strings(profile.likes).join("、")}</p>
            )}
            {Boolean(profile.world || profile.tone) && (
              <p className="muted">
                {[text(profile.world), text(profile.tone)]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
            )}
            <section className="discover-author">
              <span className="muted">角色作者</span>
              <strong>{item.author.name || "作者暂不可用"}</strong>
              <p>{item.author.bio}</p>
            </section>
            {!!scenariosOf(item).length && (
              <section>
                <h3>相处与剧情</h3>
                <div className="discover-stories">
                  {scenariosOf(item).map((scenario, i) => (
                    <div key={text(scenario.id) || i}>
                      <strong>{text(scenario.title)}</strong>
                      <small>{text(scenario.category)}</small>
                      <p>{text(scenario.subtitle)}</p>
                    </div>
                  ))}
                </div>
              </section>
            )}
            {(item.media.audition || item.media.video) && (
              <section className="discover-media">
                <h3>角色演示</h3>
                {item.media.video && (
                  <video
                    controls
                    preload="none"
                    src={item.media.video.url}
                    aria-label="角色演示视频"
                  />
                )}
                {item.media.audition && (
                  <>
                    <p>音色试听</p>
                    <audio
                      controls
                      preload="none"
                      src={item.media.audition.url}
                      aria-label="角色音色试听"
                    />
                    <small>{text(item.data.audition_text)}</small>
                  </>
                )}
              </section>
            )}
            <details className="discover-resource-details">
              <summary>模型与资源信息</summary>
              <dl>
                <dt>角色 ID</dt>
                <dd>{item.id}</dd>
                <dt>原始名称</dt>
                <dd>{text(display.originalName) || item.name}</dd>
                <dt>提供方式</dt>
                <dd>
                  {item.delivery === "oss"
                    ? `按需下载 · ${bytes(item.download_bytes)}`
                    : "App 内置"}
                </dd>
                <dt>发布版本</dt>
                <dd>{item.release_version || "无独立下载版本"}</dd>
                <dt>支持动作</dt>
                <dd>{actions.length ? actions.join("、") : "无按钮动作"}</dd>
                <dt>背景</dt>
                <dd>
                  {strings(collection.environments).join("、") || "未提供"}
                </dd>
              </dl>
              {!!voices.length && (
                <>
                  <h4>音色</h4>
                  {voices.map((v, i) => (
                    <p key={i}>
                      {text(v.title)} · {text(v.detail)}
                    </p>
                  ))}
                </>
              )}
              {!!music.length && (
                <>
                  <h4>背景音乐</h4>
                  {music.map((m, i) => (
                    <p key={i}>
                      {text(m.title)} · {text(m.detail)}
                    </p>
                  ))}
                </>
              )}
            </details>
            <button
              className="secondary"
              onClick={() => {
                close();
                navigate("character:" + item.id);
              }}
            >
              查看角色管理资料
            </button>
          </div>
        </DialogPanel>
      </div>
    </Dialog>
  );
}

export function Discovery({
  refresh,
  navigate,
}: {
  refresh: number;
  navigate: (v: string) => void;
}) {
  const { data, error, loading } = useData<DiscoveryReport>(
    "/discovery?platform=ios",
    refresh,
  );
  const [query, setQuery] = useState(""),
    [shelf, setShelf] = useState("all"),
    [category, setCategory] = useState("全部"),
    [sort, setSort] = useState("recommended"),
    [selectedID, setSelectedID] = useState("");
  const items = useMemo(
    () =>
      data?.complete
        ? discoveryResults(
            data.items,
            data.curation,
            query,
            shelf,
            category,
            sort,
          )
        : [],
    [data, query, shelf, category, sort],
  );
  const categories = data
    ? catalogueCategories(data.items, data.curation)
    : ["全部"];
  const selected = data?.items.find((item) => item.id === selectedID);
  const clear = () => {
    setQuery("");
    setShelf("all");
    setCategory("全部");
    setSort("recommended");
  };
  return (
    <div className="discover-page">
      <Heading title="发现" description="遇见心动的故事" />
      <Panel className="discover-controls">
        <div className="discover-search">
          <Search size={17} />
          <input
            aria-label="搜索发现内容"
            placeholder="搜角色、剧情或英语陪练"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          {query && (
            <button
              aria-label="清除搜索"
              className="icon-button"
              onClick={() => setQuery("")}
            >
              <X size={15} />
            </button>
          )}
        </div>
        <div
          className="discover-shelves"
          role="tablist"
          aria-label="发现内容范围"
        >
          {[
            ["all", "全部"],
            ["creators", "用户作品"],
          ].map(([id, label]) => (
            <button
              role="tab"
              key={id}
              aria-selected={shelf === id}
              className={shelf === id ? "active" : ""}
              onClick={() => setShelf(id)}
            >
              {label}
            </button>
          ))}
          <span>
            {data?.complete
              ? `${data.items.length} 位已公开角色`
              : "正在读取内容"}
          </span>
        </div>
        <div className="discover-categories" aria-label="发现分类">
          {categories.map((c) => (
            <button
              key={c}
              aria-pressed={category === c}
              className={category === c ? "active" : ""}
              onClick={() => setCategory(c)}
            >
              {c}
            </button>
          ))}
        </div>
      </Panel>
      <State loading={loading} error={error} />
      {data && !data.complete && (
        <State error="发现内容尚未完整读取，请刷新重试" />
      )}
      {data?.complete && (
        <>
          <div className="discover-result-head">
            <h2>
              {query.trim()
                ? "搜索结果"
                : shelf === "creators"
                  ? "创作者作品"
                  : "角色馆"}
              <span className="discover-count">{items.length} 位</span>
            </h2>
            <label>
              排序
              <select
                aria-label="发现排序"
                value={sort}
                onChange={(e) => setSort(e.target.value)}
              >
                <option value="recommended">推荐排序</option>
                <option value="updated">最近更新</option>
                <option value="name">角色名称</option>
              </select>
            </label>
          </div>
          {items.length ? (
            <div className="discover-grid">
              {items.map((item) => (
                <button
                  key={item.id}
                  className="discover-card"
                  aria-label={`查看${nameOf(item)}的资料`}
                  data-character-id={item.id}
                  onClick={() => setSelectedID(item.id)}
                >
                  <Cover item={item} />
                  <div className="discover-card-caption">
                    <div>
                      <strong>{nameOf(item)}</strong>
                      {item.delivery === "oss" && (
                        <ArrowDownCircle size={14} aria-label="按需下载" />
                      )}
                    </div>
                    <p>{invitationOf(item)}</p>
                  </div>
                </button>
              ))}
            </div>
          ) : (
            <Panel className="discover-empty">
              <Search size={27} />
              <h3>
                {shelf === "creators" && !query && category === "全部"
                  ? "第一份作品，等你带来"
                  : "还没有找到这样的伙伴"}
              </h3>
              <p>
                {shelf === "creators"
                  ? "公开的角色会出现在这里。也可以到全部，认识星夜的伙伴。"
                  : "试试角色名、作者名，或放宽筛选条件。"}
              </p>
              <button className="secondary" onClick={clear}>
                看看全部角色
              </button>
            </Panel>
          )}
          <button
            className="discover-create-banner"
            onClick={() => navigate("directory:characters")}
          >
            <div>
              <strong>让你的想象，也成为伙伴</strong>
              <p>创建角色，自用或分享你的作品</p>
            </div>
            <span>角色管理 →</span>
          </button>
        </>
      )}
      {selected && data && (
        <CharacterDetails
          item={selected}
          categories={categoriesOf(selected, data.curation)}
          close={() => setSelectedID("")}
          navigate={navigate}
        />
      )}
    </div>
  );
}
