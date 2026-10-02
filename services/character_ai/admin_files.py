"""Authenticated inspection of existing media. No provider calls or arbitrary paths."""

import hashlib, io, json, uuid, wave
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response

GROUPS = {
    "audio": ("对话语音", {".pcm"}),
    "voices": ("音色试听", {".wav"}),
    "models": (
        "推理模型",
        {".onnx", ".json", ".txt", ".bin", ".safetensors", ".model"},
    ),
    "trash": ("回收站", set()),
}


def checked(root, identifier):
    if not isinstance(identifier, str) or len(identifier) > 500 or "\\" in identifier:
        raise HTTPException(422, "无效文件标识")
    parts = identifier.split("/")
    if (
        len(parts) < 2
        or parts[0] not in GROUPS
        or any(p in ("", ".", "..") for p in parts)
    ):
        raise HTTPException(422, "无效文件标识")
    directory = root / ("admin-trash" if parts[0] == "trash" else parts[0])
    p = directory.joinpath(*parts[1:])
    if (
        directory.is_symlink()
        or not p.resolve().is_relative_to(directory.resolve())
        or any(
            directory.joinpath(*parts[1:i]).is_symlink()
            for i in range(2, len(parts) + 1)
        )
        or not p.is_file()
    ):
        raise HTTPException(404, "文件不存在")
    return p


def version(p):
    st = p.stat()
    return f"{st.st_size}:{st.st_mtime_ns}"


def mount_files(app, settings, store, engine, admin):
    async def auth(request: Request):
        admin(request.headers)

    router = APIRouter(prefix="/v1/admin/console/files", dependencies=[Depends(auth)])

    @router.get("")
    def listing(group: str = "audio", after: str = "", q: str = ""):
        if group not in GROUPS or len(q) > 200:
            raise HTTPException(422, "无效分类或搜索")
        folder = settings.data_dir / ("admin-trash" if group == "trash" else group)
        files = []
        for p in folder.rglob("*"):
            if not p.is_file() or p.is_symlink() or p.name.endswith(".trash-meta.json"):
                continue
            relative = p.relative_to(folder).as_posix()
            try:
                checked(settings.data_dir, group + "/" + relative)
            except HTTPException:
                continue
            if relative > after and q.lower() in relative.lower():
                files.append(p)
        files.sort(key=lambda p: p.relative_to(folder).as_posix())
        refs = {}
        if group == "voices":
            for row in store.db.execute("SELECT character,data FROM voice_design_jobs"):
                data = json.loads(row["data"])
                name = data.get("preview_file")
                if name:
                    refs[name] = dict(
                        character=row["character"], status=data.get("approved", False)
                    )
        if group == "audio":
            from .orchestrator import audio_key

            for row in store.db.execute(
                "SELECT owner,character,id,data FROM messages WHERE role='assistant' ORDER BY created DESC LIMIT 5000"
            ):
                script = json.loads(row["data"])
                if not isinstance(script,dict):continue
                voice = store.get("voice", "system", row["character"], {}) or {}
                for beat in script.get("beats", []) or []:
                    if not isinstance(beat,dict):continue
                    dialogue=beat.get("dialogue")
                    text=dialogue.get("text","") if isinstance(dialogue,dict) else (dialogue or "")
                    for revision,cache_text in (("", ""),("spoken-v2", ""),("spoken-v2",text)):
                        name = (
                            audio_key(
                                row["owner"],
                                row["character"],
                                str(voice.get("voice_id") or ""),
                                script.get("message_id") or row["id"],
                                beat.get("beat_id") or "",
                                revision=revision,
                                text=cache_text,
                            )
                            + ".pcm"
                        )
                        refs[name] = dict(
                            owner=row["owner"],
                            character=row["character"],
                            message_id=row["id"],
                            text=str(text)[:160],
                        )
        items = []
        for p in files[:50]:
            st = p.stat()
            relative = p.relative_to(folder).as_posix()
            meta = p.with_name(p.name + ".trash-meta.json")
            original = (
                json.loads(meta.read_text()).get("original")
                if group == "trash" and meta.exists()
                else None
            )
            item = dict(
                id=group + "/" + relative,
                name=relative,
                group=group,
                bytes=st.st_size,
                modified=st.st_mtime,
                version=version(p),
                reference=refs.get(p.name),
                playable=p.suffix in (".pcm", ".wav"),
                deletable=group in ("audio", "voices") or bool(original),
                original=original,
            )
            if p.suffix == ".pcm":
                item["seconds"] = st.st_size / 48000
            items.append(item)
        return dict(
            items=items,
            next=files[49].relative_to(folder).as_posix() if len(files) > 50 else "",
            total=len(files),
            groups=list(GROUPS),
        )

    @router.get("/download")
    def download(id: str, raw: bool = False):
        p = checked(settings.data_dir, id)
        if p.name.endswith(".trash-meta.json"):
            raise HTTPException(404, "不可下载内部管理信息")
        if p.suffix == ".pcm" and not raw:
            if p.stat().st_size > 20 << 20:
                raise HTTPException(413, "音频过大，请下载原始文件")
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(24000)
                wav.writeframes(p.read_bytes())
            return Response(
                buffer.getvalue(),
                media_type="audio/wav",
                headers={
                    "Content-Disposition": f'inline; filename="{p.stem}.wav"',
                    "Cache-Control": "no-store",
                },
            )
        return FileResponse(
            p,
            media_type="audio/wav"
            if p.suffix == ".wav"
            else "application/octet-stream",
            filename=p.name,
            headers={"Cache-Control": "no-store"},
        )

    @router.post("/delete")
    def delete(body: dict):
        if body.get("confirmed") is not True:
            raise HTTPException(422, "请确认文件操作及历史语音重播影响")
        p = checked(settings.data_dir, body.get("id"))
        group = body["id"].split("/")[0]
        if group == "models":
            raise HTTPException(403, "推理模型仅允许下载检查")
        if body.get("version") != version(p):
            raise HTTPException(409, "文件已变化，请刷新")
        if body.get("action") == "restore":
            if group != "trash":
                raise HTTPException(422, "请选择回收站中的文件")
            meta = p.with_name(p.name + ".trash-meta.json")
            if not meta.exists():
                raise HTTPException(409, "缺少原文件位置")
            original = json.loads(meta.read_text())["original"]
            parts = original.split("/")
            if (
                len(parts) != 2
                or parts[0] not in ("audio", "voices")
                or parts[1] in ("", ".", "..")
            ):
                raise HTTPException(422, "无效恢复位置")
            destination = settings.data_dir / parts[0] / parts[1]
            if destination.exists() or destination.is_symlink():
                raise HTTPException(409, "原位置已有文件，不覆盖")
            destination.parent.mkdir(exist_ok=True, mode=0o700)
            p.rename(destination)
            meta.unlink()
            return dict(restored=True, paid_calls=0)
        if group == "trash":
            raise HTTPException(422, "回收站支持恢复，不执行永久删除")
        if group == "voices":
            for row in store.db.execute(
                "SELECT data FROM records WHERE kind IN ('voice','voice_candidate')"
            ):
                if json.loads(row["data"]).get("preview_file") == p.name:
                    raise HTTPException(409, "当前或候选音色正在引用此试听文件")
        if len(body["id"].split("/")) != 2:
            raise HTTPException(422, "只允许回收标准声音文件")
        trash = settings.data_dir / "admin-trash"
        trash.mkdir(exist_ok=True, mode=0o700)
        destination = trash / (uuid.uuid4().hex + "-" + p.name)
        meta = destination.with_name(destination.name + ".trash-meta.json")
        meta.write_text(json.dumps({"original": body["id"]}, ensure_ascii=False))
        meta.chmod(0o600)
        try:
            p.rename(destination)
        except BaseException:
            meta.unlink(missing_ok=True)
            raise
        return dict(deleted=True, quarantined=True, paid_calls=0)

    app.include_router(router)
