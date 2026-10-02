#!/usr/bin/env python3
"""Bounded, owner-only control-room operations. No arbitrary paths or commands.

Jobs outlive the web request and write private, atomic status files. Backups and
restore candidates are verified before an active database is touched.
"""

import argparse, datetime, fcntl, hashlib, json, os, re, shlex, shutil, sqlite3, subprocess, sys, tarfile, time, uuid
from pathlib import Path
from urllib.parse import urlsplit, unquote
from activate_standby_release import environment, pg_environment

SECRET = re.compile(
    r"(?i)(password|token|api_key|secret|database_url|redis_url|access_key|authorization|cookie)"
)
PLATFORM = {
    "STARRY_ENV",
    "STARRY_LISTEN",
    "DATABASE_URL",
    "REDIS_URL",
    "REDIS_PREFIX",
    "DB_POOL_SIZE",
    "ALLOW_TEST_GUEST",
    "AI_UPSTREAM_URL",
    "AI_SERVICE_TOKEN",
    "OSS_REGION",
    "OSS_BUCKET",
    "OSS_ENDPOINT",
    "OSS_CREDENTIAL_SOURCE",
    "OSS_ACCESS_KEY_ID",
    "OSS_ACCESS_KEY_SECRET",
    "OSS_SESSION_TOKEN",
}
AI = {"api_key", "client_token", "admin_token", "host", "semantic_novelty"}
UNITS = {
    "starry-api",
    "starry-ai",
    "starry-admin",
    "starry-edge",
    "starry-postgres",
    "starry-redis",
    "starry-certificate-renew",
}
EXTENSIONS = {
    ".glb",
    ".vrm",
    ".fbx",
    ".gltf",
    ".bin",
    ".bundle",
    ".assetbundle",
    ".json",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".wav",
    ".mp3",
    ".ogg",
    ".m4a",
    ".zip",
    ".tga",
    ".dds",
    ".ktx2",
    ".txt",
}


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with temp.open("x") as f:
        os.chmod(temp, 0o600)
        f.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


def safe(root, relative, exists=True):
    if (
        not isinstance(relative, str)
        or len(relative) > 800
        or "\\" in relative
        or "\x00" in relative
    ):
        raise ValueError("无效文件路径")
    parts = Path(relative).parts
    if (
        not parts
        or Path(relative).is_absolute()
        or any(p in (".", "..") for p in parts)
    ):
        raise ValueError("不允许跨目录访问")
    p = root / relative
    if not p.resolve().is_relative_to(root.resolve()) or any(
        (root.joinpath(*parts[:i])).is_symlink() for i in range(1, len(parts) + 1)
    ):
        raise ValueError("不允许符号链接或越界访问")
    if exists and not p.exists():
        raise ValueError("文件不存在")
    return p


def masked(data):
    if isinstance(data, dict):
        return {
            k: ({"configured": bool(v)} if SECRET.search(k) else masked(v))
            for k, v in data.items()
        }
    if isinstance(data, list):
        return [masked(v) for v in data]
    return data


def run(args, **kw):
    result = subprocess.run(
        [str(a) for a in args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kw
    )
    if result.returncode:
        raise ValueError("操作命令失败，请检查服务状态与任务记录")
    return result.stdout


def status(path, state, **values):
    data = json.loads(path.read_text())
    data.update(state=state, updated=now(), **values)
    atomic(path, data)


def config_version(root):
    h = hashlib.sha256()
    for name in ("platform.env", "ai-settings.json"):
        p = root / "config" / name
        if p.exists():
            h.update(p.read_bytes())
    return h.hexdigest()


def config_read(root):
    platform = file_environment(root / "config/platform.env")
    ai = json.loads((root / "config/ai-settings.json").read_text())
    return dict(
        version=config_version(root),
        platform=masked(platform),
        ai=masked(ai),
        platform_edit=sorted(
            PLATFORM - {"STARRY_LISTEN", "REDIS_PREFIX", "AI_UPSTREAM_URL"}
        ),
        ai_edit=sorted(AI),
        routing="\n".join(
            "[含凭据，已隐藏]" if SECRET.search(line) else line
            for line in (root / "config/Caddyfile").read_text().splitlines()
        ),
        note="空白凭据保留原值。保存会校验连接并创建配置备份；应用是独立任务。",
    )


def env_write(path, values):
    content = "".join(
        k + "=" + shlex.quote(str(v)) + "\n" for k, v in sorted(values.items())
    )
    tmp = path.with_suffix(".candidate")
    tmp.write_text(content)
    tmp.chmod(0o600)
    os.replace(tmp, path)


def file_environment(path):
    values = {}
    for line in path.read_text().splitlines():
        words = shlex.split(line)
        if len(words) == 1 and "=" in words[0]:
            k, v = words[0].split("=", 1)
            values[k] = v
    return values


def save_config(root, release, body):
    lock = root / "data/admin/configuration.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        if (root / "data/admin/maintenance.json").exists():
            raise ValueError("维护期间不能修改配置")
        return save_config_locked(root, release, body)


def save_config_locked(root, release, body):
    if body.get("expected_version") != config_version(root):
        raise ValueError("配置已经变化，请刷新后编辑")
    original = file_environment(root / "config/platform.env")
    ai = json.loads((root / "config/ai-settings.json").read_text())
    new = dict(original)
    updated = dict(ai)
    for k, v in body.get("platform", {}).items():
        if k not in PLATFORM - {"STARRY_LISTEN", "REDIS_PREFIX", "AI_UPSTREAM_URL"}:
            raise ValueError("该平台字段不能在线修改")
        if (
            not isinstance(v, str)
            or len(v) > 8192
            or any(x in v for x in ("\r", "\n", "\x00"))
        ):
            raise ValueError("无效平台字段")
        if SECRET.search(k) and not v:
            continue
        new[k] = v
    for k, v in body.get("ai", {}).items():
        if k not in AI:
            raise ValueError("该 AI 字段请在模型与预算页面编辑")
        if k == "semantic_novelty":
            if type(v) is not bool:
                raise ValueError("语义去重必须为布尔值")
        elif (
            not isinstance(v, str)
            or len(v) > 8192
            or any(x in v for x in ("\r", "\n", "\x00"))
        ):
            raise ValueError("无效 AI 字段")
        if SECRET.search(k) and not v:
            continue
        updated[k] = v
    if not re.fullmatch(r"https://[a-z0-9.-]+\.aliyuncs\.com", updated.get("host", "")):
        raise ValueError("模型提供商必须为阿里云 HTTPS 端点")
    if "client_token" in body.get("ai", {}) and body["ai"]["client_token"]:
        new["AI_SERVICE_TOKEN"] = updated["client_token"]
    elif (
        "AI_SERVICE_TOKEN" in body.get("platform", {})
        and body["platform"]["AI_SERVICE_TOKEN"]
    ):
        updated["client_token"] = new["AI_SERVICE_TOKEN"]
    for k in ("OSS_CREDENTIAL_SOURCE",):
        if new.get(k, "ecs") not in ("ecs", "env"):
            raise ValueError("OSS 凭据来源仅支持 ecs/env")
    validation = os.environ | new
    run([release / "bin/starry-admin", "--validate-config"], env=validation, timeout=15)
    backup = (
        root
        / "backups"
        / (
            "configuration-"
            + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            + "-"
            + uuid.uuid4().hex[:6]
        )
    )
    backup.mkdir(mode=0o700)
    for name in ("platform.env", "ai-settings.json"):
        shutil.copy2(root / "config" / name, backup / name)
    old_version = config_version(root)
    try:
        env_write(root / "config/platform.env", new)
        atomic(root / "config/ai-settings.json", updated)
    except BaseException:
        for name in ("platform.env", "ai-settings.json"):
            shutil.copy2(backup / name, root / "config" / name)
        raise
    atomic(
        root / "data/admin/config-state.json",
        dict(
            backup=backup.name,
            saved_version=config_version(root),
            previous_version=old_version,
        ),
    )
    # SDK env credentials must also be seen by the admin process after apply.
    return dict(
        saved=True,
        version=config_version(root),
        backup=backup.name,
        restart_required=True,
    )


def backup_info(root, name):
    folder = safe(root / "backups", name)
    files = []
    for p in sorted(folder.rglob("*")):
        if p.is_file() and not p.is_symlink():
            files.append(
                dict(name=p.relative_to(folder).as_posix(), bytes=p.stat().st_size)
            )
    modern = folder / "control-room-manifest.json"
    return dict(
        id=name,
        created=folder.stat().st_mtime,
        files=files,
        bytes=sum(p["bytes"] for p in files),
        restorable=modern.exists() and (folder / "platform.dump").exists(),
        legacy=not modern.exists(),
    )


def verify_backup(root, name):
    folder = safe(root / "backups", name)
    manifest = json.loads((folder / "control-room-manifest.json").read_text())
    if manifest.get("schema") != 1:
        raise ValueError("不支持的备份格式")
    for relative, info in manifest["files"].items():
        p = safe(folder, relative)
        if (
            not p.is_file()
            or p.stat().st_size != info["bytes"]
            or sha(p) != info["sha256"]
        ):
            raise ValueError("备份校验不通过：" + relative)
    if (
        "platform.dump" not in manifest["files"]
        or "ai-state.sqlite3" not in manifest["files"]
        or "media.tar.gz" not in manifest["files"]
    ):
        raise ValueError("缺少数据库备份")
    with sqlite3.connect(folder / "ai-state.sqlite3") as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("AI 数据库完整性检查失败")
    with tarfile.open(folder / "media.tar.gz") as archive:
        for member in archive.getmembers():
            if (
                member.issym()
                or member.islnk()
                or not (member.isdir() or member.isfile())
            ):
                raise ValueError("备份包含不支持的文件类型")
            safe(folder / "extract-test", member.name, exists=False)
    return manifest


def service(*args):
    return run(["systemctl", "--user", *args], timeout=30)


def ready(url, timeout=45):
    import urllib.request

    client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with client.open(url, timeout=2) as r:
                if r.status == 200:
                    return
        except OSError:
            pass
        time.sleep(0.4)
    raise ValueError("服务就绪检查失败")


def create_backup(root, release, quiet=False):
    env = environment(root / "config/platform.env")
    ai = json.loads((root / "config/ai-settings.json").read_text())
    data = Path(ai["data_dir"])
    name = (
        "control-room-"
        + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid.uuid4().hex[:6]
    )
    folder = root / "backups" / name
    folder.mkdir(mode=0o700, parents=True)
    if not quiet:
        service("stop", "starry-api", "starry-ai")
    try:
        run(
            [root / "postgres/bin/pg_dump", "-Fc", "--file", folder / "platform.dump"],
            env=pg_environment(env),
            timeout=180,
        )
        with (
            sqlite3.connect(data / "state.sqlite3") as source,
            sqlite3.connect(folder / "ai-state.sqlite3") as target,
        ):
            source.backup(target)
        with tarfile.open(folder / "media.tar.gz", "w:gz") as archive:
            for entry in data.iterdir():
                if entry.name in (
                    "state.sqlite3",
                    "state.sqlite3-wal",
                    "state.sqlite3-shm",
                ) or entry.name.endswith(".tmp"):
                    continue
                archive.add(
                    entry,
                    arcname="ai/" + entry.name,
                    filter=lambda m: None if m.issym() or m.islnk() else m,
                )
            if (root / "data/library-trash").exists():
                archive.add(
                    root / "data/library-trash",
                    arcname="library-trash",
                    filter=lambda m: None if m.issym() or m.islnk() else m,
                )
            if (root / "data/library").exists():
                archive.add(
                    root / "data/library",
                    arcname="library",
                    filter=lambda m: None if m.issym() or m.islnk() else m,
                )
        cfg = folder / "config"
        cfg.mkdir(mode=0o700)
        for p in (root / "config").glob("*"):
            if (
                p.is_file()
                and not p.is_symlink()
                and p.suffix in (".env", ".json", ".conf")
            ):
                shutil.copy2(p, cfg / p.name)
        files = {
            p.relative_to(folder).as_posix(): dict(
                bytes=p.stat().st_size, sha256=sha(p)
            )
            for p in folder.rglob("*")
            if p.is_file()
        }
        atomic(
            folder / "control-room-manifest.json",
            dict(
                schema=1,
                created=now(),
                files=files,
                release=release.name,
                redis_sessions="not restored; all app sessions are revoked on restore",
            ),
        )
        verify_backup(root, folder.name)
    finally:
        if not quiet:
            service("start", "starry-api", "starry-ai")
            ready("http://127.0.0.1:8090/health/ready")
            ready("http://127.0.0.1:8766/health")
    return backup_info(root, folder.name)


def restore_candidate(root, release, folder, candidate):
    env = environment(root / "config/platform.env")
    pg = pg_environment(env)
    run([root / "postgres/bin/createdb", candidate], env=pg, timeout=20)
    try:
        run(
            [
                root / "postgres/bin/pg_restore",
                "--dbname",
                candidate,
                "--exit-on-error",
                "--no-owner",
                folder / "platform.dump",
            ],
            env=pg,
            timeout=180,
        )
        from urllib.parse import urlunsplit

        u = urlsplit(env["DATABASE_URL"])
        candidate_env = env | {
            "DATABASE_URL": urlunsplit(u._replace(path="/" + candidate))
        }
        run([release / "bin/starry-migrate"], env=candidate_env, timeout=30)
        # Control-room credentials and audit stay current even when business
        # data travels back in time. No loss of the operator's access.
        current = run(
            [
                root / "postgres/bin/pg_dump",
                "--data-only",
                "--table=admin_users",
                "--table=admin_audit",
            ],
            env=pg,
            timeout=30,
        )
        clean = pg_environment(env, candidate)
        run(
            [
                root / "postgres/bin/psql",
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                "TRUNCATE admin_audit,admin_users",
            ],
            env=clean,
            timeout=15,
        )
        run(
            [root / "postgres/bin/psql", "-v", "ON_ERROR_STOP=1"],
            env=clean,
            input=current,
            timeout=30,
        )
        sequence = int(
            run(
                [
                    root / "postgres/bin/psql",
                    "-Atq",
                    "-c",
                    "SELECT last_value FROM starry_registration_sequence",
                ],
                env=pg,
                timeout=15,
            ).strip()
        )
        run(
            [
                root / "postgres/bin/psql",
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                f"SELECT setval('starry_registration_sequence',GREATEST(last_value,{sequence}),true) FROM starry_registration_sequence;",
            ],
            env=clean,
            timeout=15,
        )
        aliases = run(
            [
                root / "postgres/bin/psql",
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                "COPY account_handles TO STDOUT WITH CSV",
            ],
            env=pg,
            timeout=15,
        )
        reserve = (
            b"CREATE TEMP TABLE live_handles(LIKE account_handles);\nCOPY live_handles FROM STDIN WITH CSV;\n"
            + aliases
            + b"\\.\nINSERT INTO account_handles(handle,user_id,assigned_at,retired_at) SELECT h.handle,NULL,h.assigned_at,COALESCE(h.retired_at,now()) FROM live_handles h WHERE NOT EXISTS(SELECT 1 FROM account_handles a WHERE a.handle=h.handle);\n"
        )
        run(
            [root / "postgres/bin/psql", "-v", "ON_ERROR_STOP=1"],
            env=clean,
            input=reserve,
            timeout=15,
        )
        epochs = run(
            [
                root / "postgres/bin/psql",
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                "COPY (SELECT id,session_epoch FROM users) TO STDOUT WITH CSV",
            ],
            env=pg,
            timeout=15,
        )
        sql = (
            b"CREATE TEMP TABLE current_epochs(id uuid,epoch bigint);\nCOPY current_epochs FROM STDIN WITH CSV;\n"
            + epochs
            + b"\\.\nUPDATE users u SET session_epoch=GREATEST(u.session_epoch,COALESCE((SELECT epoch FROM current_epochs e WHERE e.id=u.id),0))+1; UPDATE admin_users SET session_epoch=session_epoch+1;\n"
        )
        run(
            [root / "postgres/bin/psql", "-v", "ON_ERROR_STOP=1"],
            env=clean,
            input=sql,
            timeout=15,
        )
    except BaseException:
        run(
            [root / "postgres/bin/dropdb", "--if-exists", candidate], env=pg, timeout=20
        )
        raise
    return env


def restore_backup(root, release, name, job):
    manifest = verify_backup(root, name)
    folder = safe(root / "backups", name)
    status(job, "running", stage="创建恢复前保护备份")
    safety = create_backup(root, release)
    status(job, "running", stage="验证独立候选数据库", safety_backup=safety["id"])
    candidate = "starry_restore_" + uuid.uuid4().hex[:12]
    env = restore_candidate(root, release, folder, candidate)
    pg = pg_environment(env)
    original = pg["PGDATABASE"]
    previous = "starry_before_restore_" + uuid.uuid4().hex[:12]
    if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", original):
        raise ValueError("数据库名称不支持安全切换")
    data = Path(json.loads((root / "config/ai-settings.json").read_text())["data_dir"])
    staging = root / "data" / ("restore-" + uuid.uuid4().hex)
    staging.mkdir(mode=0o700)
    with tarfile.open(folder / "media.tar.gz") as archive:
        archive.extractall(staging, filter="data")
    (staging / "ai").mkdir(exist_ok=True)
    shutil.copy2(folder / "ai-state.sqlite3", staging / "ai/state.sqlite3")
    for suffix in ("-wal", "-shm"):
        (staging / ("ai/state.sqlite3" + suffix)).unlink(missing_ok=True)
    library = root / "data/library"
    library_trash = root / "data/library-trash"
    old_trash = root / "data" / ("library-trash-before-" + uuid.uuid4().hex[:8])
    old_data = data.with_name(data.name + "-before-" + uuid.uuid4().hex[:8])
    old_library = root / "data" / ("library-before-" + uuid.uuid4().hex[:8])
    switched = False
    renamed = False
    status(job, "running", stage="切换数据，服务短暂维护")
    service("stop", "starry-api", "starry-ai", "starry-admin")
    try:
        admin = pg_environment(env, "postgres")
        run(
            [
                root / "postgres/bin/psql",
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname IN ('{original}','{candidate}') AND pid<>pg_backend_pid();",
            ],
            env=admin,
            timeout=15,
        )
        run(
            [
                root / "postgres/bin/psql",
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                f'ALTER DATABASE "{original}" RENAME TO "{previous}";',
            ],
            env=admin,
            timeout=15,
        )
        renamed = True
        run(
            [
                root / "postgres/bin/psql",
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                f'ALTER DATABASE "{candidate}" RENAME TO "{original}";',
            ],
            env=admin,
            timeout=15,
        )
        switched = True
        data.rename(old_data)
        (staging / "ai").rename(data)
        library = root / "data/library"
        if library.exists():
            library.rename(old_library)
        if (staging / "library").exists():
            (staging / "library").rename(library)
        if library_trash.exists():
            library_trash.rename(old_trash)
        if (staging / "library-trash").exists():
            (staging / "library-trash").rename(library_trash)
        service("start", "starry-api", "starry-ai", "starry-admin")
        ready("http://127.0.0.1:8090/health/ready")
        ready("http://127.0.0.1:8766/health")
        ready("http://127.0.0.1:8100/health/ready")
    except BaseException:
        service("stop", "starry-api", "starry-ai", "starry-admin")
        admin = pg_environment(env, "postgres")
        if switched:
            run(
                [
                    root / "postgres/bin/psql",
                    "-v",
                    "ON_ERROR_STOP=1",
                    "-c",
                    f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='{original}' AND pid<>pg_backend_pid();",
                ],
                env=admin,
            )
            failed = "starry_failed_restore_" + uuid.uuid4().hex[:8]
            run(
                [
                    root / "postgres/bin/psql",
                    "-v",
                    "ON_ERROR_STOP=1",
                    "-c",
                    f'ALTER DATABASE "{original}" RENAME TO "{failed}"; ALTER DATABASE "{previous}" RENAME TO "{original}";',
                ],
                env=admin,
            )
        elif renamed:
            run(
                [
                    root / "postgres/bin/psql",
                    "-v",
                    "ON_ERROR_STOP=1",
                    "-c",
                    f'ALTER DATABASE "{previous}" RENAME TO "{original}";',
                ],
                env=admin,
            )
        if old_data.exists():
            if data.exists():
                data.rename(
                    data.with_name(data.name + "-failed-" + uuid.uuid4().hex[:8])
                )
            old_data.rename(data)
        if old_library.exists():
            if library.exists():
                library.rename(
                    library.with_name("library-failed-" + uuid.uuid4().hex[:8])
                )
            old_library.rename(library)
        if old_trash.exists():
            if library_trash.exists():
                library_trash.rename(
                    library_trash.with_name(
                        "library-trash-failed-" + uuid.uuid4().hex[:8]
                    )
                )
            old_trash.rename(library_trash)
        service("start", "starry-api", "starry-ai", "starry-admin")
        raise
    return dict(
        restored=name,
        safety_backup=safety["id"],
        previous_database=previous,
        sessions_revoked=True,
        configuration="current credentials and endpoints retained",
    )


def execute_job(root, release, identifier):
    path = safe(root / "data/admin/jobs", identifier + ".json")
    job = json.loads(path.read_text())
    operation = job["operation"]
    body = job["input"]
    lock = root / "data/admin/operations.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        status(path, "running", stage="开始执行")
        maintenance = root / "data/admin/maintenance.json"
        atomic(maintenance, dict(job_id=identifier, started=now()))
        try:
            if operation == "backup":
                result = create_backup(root, release)
            elif operation == "verify-backup":
                result = dict(verified=True, manifest=verify_backup(root, body["id"]))
            elif operation == "restore":
                result = restore_backup(root, release, body["id"], path)
            elif operation == "apply-config":
                state = json.loads((root / "data/admin/config-state.json").read_text())
                if config_version(root) != state["saved_version"]:
                    raise ValueError("配置已变化，请重新保存后应用")
                try:
                    service("restart", "starry-api", "starry-ai", "starry-admin")
                    ready("http://127.0.0.1:8090/health/ready")
                    ready("http://127.0.0.1:8766/health")
                    ready("http://127.0.0.1:8100/health/ready")
                except BaseException:
                    backup = safe(root / "backups", state["backup"])
                    for name in ("platform.env", "ai-settings.json"):
                        shutil.copy2(backup / name, root / "config" / name)
                    service("restart", "starry-api", "starry-ai", "starry-admin")
                    raise ValueError("新配置就绪失败，已恢复原配置并重启服务")
                result = dict(applied=True)
            elif operation == "renew-certificate":
                service("start", "starry-certificate-renew")
                result = dict(started=True)
            elif operation == "restart-service":
                unit = body.get("unit")
                if unit not in UNITS:
                    raise ValueError("服务不在允许列表")
                service("restart", unit)
                result = dict(restarted=unit)
            elif operation == "activate-release":
                target = safe(release.parent, body["id"])
                run(
                    [
                        sys.executable,
                        target / "scripts/deploy/upgrade_active_api.py",
                        "--release",
                        target,
                        "--restart-ai",
                    ],
                    timeout=240,
                )
                result = dict(activated=target.name)
            else:
                raise ValueError("不支持的维护任务")
            status(path, "succeeded", stage="已完成", result=result)
        except BaseException as e:
            # Exceptions never contain subprocess stderr or configuration values.
            message = (
                str(e)
                if isinstance(e, ValueError)
                else "维护失败，原数据与保护备份已保留"
            )
            status(path, "failed", error=message[:300])
        finally:
            maintenance.unlink(missing_ok=True)


def queue(root, release, operation, body):
    identifier = str(uuid.uuid4())
    path = root / "data/admin/jobs" / (identifier + ".json")
    atomic(
        path,
        dict(
            id=identifier,
            operation=operation,
            state="queued",
            created=now(),
            updated=now(),
            input=body,
        ),
    )
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--root",
        str(root),
        "--release",
        str(release),
        "--execute-job",
        identifier,
    ]
    try:
        # A separate finite systemd unit survives restarting the web service.
        run(
            [
                "systemd-run",
                "--user",
                "--quiet",
                "--collect",
                "--unit=starry-admin-task-" + identifier,
                "--property=UMask=0077",
                "--property=Type=exec",
                *command,
            ],
            timeout=10,
        )
    except BaseException:
        status(path, "failed", error="无法启动独立维护任务")
        raise ValueError("无法启动独立维护任务")
    return dict(job_id=identifier, state="queued")


def dispatch(root, release, action, body):
    if action.startswith("write-") or action in ("prepare-upload", "finish-upload"):
        lock = root / "data/admin/operations.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        with lock.open("a") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError("另一项维护或写入正在执行，请稍后重试")
            return dispatch_action(root, release, action, body)
    return dispatch_action(root, release, action, body)


def dispatch_action(root, release, action, body):
    if action == "read-config":
        return config_read(root)
    if action == "write-config":
        if body.get("operation") == "apply":
            return queue(root, release, "apply-config", {})
        return save_config(root, release, body)
    if action == "read-backups":
        items = [
            backup_info(root, p.name)
            for p in sorted((root / "backups").iterdir(), reverse=True)
            if p.is_dir() and not p.is_symlink()
        ]
        for p in sorted((root / "backups-trash").glob("*"), reverse=True):
            if p.is_dir() and not p.is_symlink():
                d = dict(
                    id=p.name,
                    created=p.stat().st_mtime,
                    bytes=sum(
                        x.stat().st_size
                        for x in p.rglob("*")
                        if x.is_file() and not x.is_symlink()
                    ),
                    quarantined=True,
                    files=[],
                    restorable=False,
                )
                items.append(d)
        return dict(items=items)
    if action == "write-backups":
        operation = body.get("operation")
        if operation in ("backup", "verify-backup", "restore"):
            if (
                operation == "restore"
                and body.get("confirmation") != "恢复全部业务数据"
            ):
                raise ValueError("请输入恢复全部业务数据确认")
            return queue(root, release, operation, {"id": body.get("id")})
        if operation == "recover":
            folder = safe(root / "backups-trash", body["id"])
            destination = root / "backups" / folder.name
            if destination.exists():
                raise ValueError("备份位置已占用")
            folder.rename(destination)
            return dict(recovered=True)
        if operation == "delete":
            folder = safe(root / "backups", body.get("id"))
            active = root / "data/admin/maintenance.json"
            if active.exists():
                raise ValueError("维护期间不能删除备份")
            if not folder.is_dir():
                raise ValueError("无效备份")
            trash = root / "backups-trash"
            trash.mkdir(exist_ok=True, mode=0o700)
            folder.rename(trash / (folder.name + "-" + uuid.uuid4().hex[:6]))
            return dict(deleted=True, quarantined=True)
        raise ValueError("不支持的备份操作")
    if action == "read-jobs":
        folder = root / "data/admin/jobs"
        items = []
        for p in sorted(folder.glob("*.json"), reverse=True):
            d = json.loads(p.read_text())
            d.pop("input", None)
            items.append(d)
        return dict(
            items=sorted(items, key=lambda x: x["created"], reverse=True)[:100],
            maintenance=(root / "data/admin/maintenance.json").exists(),
        )
    if action == "read-releases":
        items = []
        for p in sorted(release.parent.iterdir(), reverse=True):
            if p.is_dir() and not p.is_symlink() and (p / "release.json").exists():
                d = json.loads((p / "release.json").read_text())
                items.append(
                    dict(
                        id=p.name,
                        commit=d.get("source_commit"),
                        current=p.resolve() == release.resolve(),
                        files=len(d.get("files", {})),
                    )
                )
        return dict(items=items)
    if action == "write-releases":
        return queue(root, release, "activate-release", {"id": body.get("id")})
    if action == "read-certificates":
        items = []
        for p in (root / "config/certbot/live").glob("*/cert.pem"):
            info = run(
                [
                    "openssl",
                    "x509",
                    "-in",
                    p,
                    "-noout",
                    "-dates",
                    "-subject",
                    "-issuer",
                    "-fingerprint",
                    "-sha256",
                ]
            ).decode()
            items.append(dict(name=p.parent.name, information=info))
        return dict(items=items)
    if action == "write-certificates":
        return queue(root, release, "renew-certificate", {})
    if action == "write-services":
        return queue(root, release, "restart-service", {"unit": body.get("unit")})
    library = root / "data/library"
    if action == "read-library":
        items = []
        source = (
            root / "data/library-trash" if body.get("folder") == "trash" else library
        )
        for p in sorted(source.glob("*/metadata.json")):
            d = json.loads(p.read_text())
            d["quarantined"] = source != library
            if (
                d["id"] > body.get("after", "")
                and body.get("q", "").lower()
                in json.dumps(d, ensure_ascii=False).lower()
            ):
                items.append(d)
        return dict(items=items[:50], next=items[49]["id"] if len(items) > 50 else "")
    if action == "prepare-upload":
        name = body.get("name", "")
        if (
            not re.fullmatch(r"[\w .()\u4e00-\u9fff-]{1,160}", name)
            or Path(name).suffix.lower() not in EXTENSIONS
        ):
            raise ValueError("不支持的资源名称或格式")
        identifier = str(uuid.uuid4())
        folder = library / identifier
        folder.mkdir(parents=True, mode=0o700)
        d = dict(
            id=identifier,
            version=1,
            name=name,
            file="content" + Path(name).suffix.lower(),
            character_id=body.get("character_id", ""),
            status="pending",
            created=now(),
        )
        atomic(folder / "metadata.json", d)
        return dict(id=identifier, path=str(folder / d["file"]))
    if action == "finish-upload":
        folder = safe(library, body["id"])
        meta = folder / "metadata.json"
        d = json.loads(meta.read_text())
        p = folder / d["file"]
        if sha(p) != body["sha256"] or p.stat().st_size != body["bytes"]:
            raise ValueError("上传校验失败")
        d.update(sha256=body["sha256"], bytes=body["bytes"], status="ready")
        atomic(meta, d)
        return d
    if action == "write-library":
        if body.get("operation") == "restore":
            folder = safe(root / "data/library-trash", body["id"])
            destination = library / folder.name
            if destination.exists():
                raise ValueError("原位置已有文件，不覆盖")
            folder.rename(destination)
            return dict(restored=True)
        folder = safe(library, body["id"])
        d = json.loads((folder / "metadata.json").read_text())
        if body.get("operation") == "metadata":
            if body.get("expected_version") != d.get("version", 1):
                raise ValueError("资源信息已变化，请刷新")
            for field in ("character_id", "description", "tags"):
                if field in body:
                    d[field] = body[field]
            d["version"] = d.get("version", 1) + 1
            atomic(folder / "metadata.json", d)
            return d
        if body.get("operation") == "delete":
            trash = root / "data/library-trash"
            trash.mkdir(exist_ok=True, mode=0o700)
            folder.rename(trash / folder.name)
            return dict(deleted=True)
        raise ValueError("不支持的资源操作")
    if action == "resolve-download":
        kind = body.get("kind")
        if kind == "library":
            folder = safe(
                root / "data/library-trash"
                if body.get("folder") == "trash"
                else library,
                body["id"],
            )
            d = json.loads((folder / "metadata.json").read_text())
            p = safe(folder, d["file"])
            return dict(path=str(p), name=d["name"])
        if kind == "backup":
            folder = safe(root / "backups", body["id"])
            p = safe(folder, body["file"])
            if p.name not in (
                "platform.dump",
                "ai-state.sqlite3",
                "media.tar.gz",
                "control-room-manifest.json",
                "redis.rdb",
                "manifest.json",
            ):
                raise ValueError("该备份文件不提供直接下载")
            return dict(path=str(p), name=p.name)
        raise ValueError("不支持的下载")
    if action == "read-files":
        roots = {
            "release": release,
            "config": root / "config",
            "backups": root / "backups",
            "library": library,
            "admin": root / "data/admin",
            "ai": Path(
                json.loads((root / "config/ai-settings.json").read_text())["data_dir"]
            ),
        }
        group = body.get("folder") or "release"
        if group not in roots:
            raise ValueError("目录不在允许列表")
        after = body.get("after", "")
        q = body.get("q", "").lower()
        items = []
        for p in sorted(roots[group].rglob("*")):
            if p.is_file() and not p.is_symlink():
                name = p.relative_to(roots[group]).as_posix()
                if name > after and q in name.lower():
                    items.append(
                        dict(
                            name=name,
                            bytes=p.stat().st_size,
                            modified=p.stat().st_mtime,
                            permission=oct(p.stat().st_mode & 0o777),
                        )
                    )
        return dict(
            items=items[:100],
            next=items[99]["name"] if len(items) > 100 else "",
            folder=group,
        )
    if action == "read-connections":
        env = environment(root / "config/platform.env")
        items = []
        for key in ("DATABASE_URL", "REDIS_URL", "AI_UPSTREAM_URL"):
            u = urlsplit(env.get(key, ""))
            items.append(
                dict(
                    name=key,
                    scheme=u.scheme,
                    host=u.hostname,
                    port=u.port,
                    credentials_configured=bool(u.password),
                )
            )
        return dict(items=items)
    raise ValueError("不支持的管理操作")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--action")
    parser.add_argument("--execute-job")
    args = parser.parse_args()
    os.umask(0o077)
    root = args.root.resolve()
    release = args.release.resolve()
    if args.execute_job:
        execute_job(root, release, args.execute_job)
        return
    try:
        body = json.loads(sys.stdin.read(1 << 20) or "{}")
        result = dispatch(root, release, args.action, body)
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, KeyError, FileNotFoundError, json.JSONDecodeError) as error:
        print(
            json.dumps(
                {
                    "error": str(error)
                    if isinstance(error, ValueError)
                    else "所需文件或字段不存在"
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
