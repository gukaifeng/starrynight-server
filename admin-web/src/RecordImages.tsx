import { useEffect, useState } from "react";
import { Dialog, DialogPanel, DialogTitle } from "@headlessui/react";
import { Image as ImageIcon, Maximize2, X } from "lucide-react";
import type { Resource, Row } from "./api";

type Identity = {
  kind: "character" | "user" | "author";
  id: string;
  name: string;
};
const object = (value: unknown): Row =>
  value && typeof value === "object" ? (value as Row) : {};
const text = (value: unknown) => (typeof value === "string" ? value : "");
export function recordIdentity(resource: Resource, row: Row): Identity | null {
  const profile = object(row.profile),
    data = object(row.data);
  if (
    resource.id === "characters" ||
    (resource.ai && resource.id === "profiles")
  )
    return {
      kind: "character",
      id: text(row.id),
      name: text(row.name) || text(row.id),
    };
  if (resource.id === "users" || resource.id === "account_avatars")
    return {
      kind: "user",
      id: text(row.id ?? row.user_id),
      name: text(profile.display_name) || text(row.starry_id) || "用户",
    };
  if (resource.id === "authors")
    return {
      kind: "author",
      id: text(row.id),
      name: text(data.name) || text(row.id),
    };
  return null;
}
export function imageURL(
  identity: Identity,
  variant = "avatar",
  revision: unknown = "",
) {
  return (
    "/admin-api/v1/record-images/" +
    identity.kind +
    "/" +
    encodeURIComponent(identity.id) +
    "/" +
    variant +
    "?revision=" +
    encodeURIComponent(String(revision))
  );
}

export function RecordAvatar({
  identity,
  revision = "",
  className = "",
}: {
  identity: Identity;
  revision?: unknown;
  className?: string;
}) {
  const src = imageURL(identity, "avatar", revision);
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [src]);
  return (
    <span className={"record-avatar " + className}>
      {failed ? (
        <span className="avatar-fallback" aria-label="暂无头像">
          {identity.name.slice(0, 1) || <ImageIcon size={15} />}
        </span>
      ) : (
        <img
          src={src}
          alt={identity.name + "的头像"}
          loading="lazy"
          decoding="async"
          onError={() => setFailed(true)}
        />
      )}
    </span>
  );
}

export function RecordReference({
  kind,
  id,
  revision,
}: {
  kind: Identity["kind"];
  id: string;
  revision?: unknown;
}) {
  return (
    <div className="record-reference">
      <RecordAvatar identity={{ kind, id, name: id }} revision={revision} />
      <span className="mono">{id}</span>
    </div>
  );
}

function Artwork({
  identity,
  variant,
  revision,
  open,
}: {
  identity: Identity;
  variant: string;
  revision?: unknown;
  open: (src: string, title: string) => void;
}) {
  const src = imageURL(identity, variant, revision),
    title = variant === "cover" ? "角色封面" : "头像";
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [src]);
  return (
    <div className={"record-artwork " + variant}>
      <button
        className="artwork-open"
        disabled={failed}
        onClick={() => open(src, identity.name + " · " + title)}
        aria-label={"放大查看" + title}
      >
        {failed ? (
          <span className="artwork-missing">
            <ImageIcon size={24} />
            <span>尚未提供{title}</span>
          </span>
        ) : (
          <img
            src={src}
            alt={identity.name + "的" + title}
            decoding="async"
            onError={() => setFailed(true)}
          />
        )}
        {!failed && (
          <span className="artwork-expand">
            <Maximize2 size={13} />
            查看大图
          </span>
        )}
      </button>
      <span className="artwork-caption">{title}</span>
    </div>
  );
}

export function RecordGallery({
  resource,
  row,
  revision,
}: {
  resource: Resource;
  row: Row;
  revision?: unknown;
}) {
  const identity = recordIdentity(resource, row);
  const [preview, setPreview] = useState<{ src: string; title: string } | null>(
    null,
  );
  if (!identity?.id) return null;
  const open = (src: string, title: string) => setPreview({ src, title });
  return (
    <>
      <div
        className={
          "record-gallery " + (identity.kind === "character" ? "has-cover" : "")
        }
      >
        {identity.kind === "character" && (
          <Artwork
            identity={identity}
            variant="cover"
            revision={revision}
            open={open}
          />
        )}
        <Artwork
          identity={identity}
          variant="avatar"
          revision={revision}
          open={open}
        />
      </div>
      <Dialog
        open={!!preview}
        onClose={() => setPreview(null)}
        className="image-dialog"
      >
        <div className="image-dialog-shade" />
        <div className="image-dialog-position">
          <DialogPanel className="image-dialog-panel">
            <div className="image-dialog-header">
              <DialogTitle>{preview?.title}</DialogTitle>
              <button
                className="icon-button"
                aria-label="关闭图片预览"
                onClick={() => setPreview(null)}
              >
                <X size={19} />
              </button>
            </div>
            {preview && (
              <img
                src={preview.src}
                alt={preview.title}
                className="image-original"
              />
            )}
            <p>图片来自服务器私有资源，点击空白处或按 Esc 返回。</p>
          </DialogPanel>
        </div>
      </Dialog>
    </>
  );
}
