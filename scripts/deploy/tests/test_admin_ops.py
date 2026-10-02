"""Private-operation tests. PostgreSQL cases require a disposable *_test DB."""

import importlib.util, json, os, shlex, sqlite3, sys, tarfile, uuid
from pathlib import Path
import pytest

DEPLOY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEPLOY))
spec = importlib.util.spec_from_file_location("admin_ops", DEPLOY / "admin_ops.py")
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)


@pytest.fixture
def runtime(tmp_path):
    root = tmp_path / "app"
    (root / "config").mkdir(parents=True)
    (root / "data/ai/audio").mkdir(parents=True)
    (root / "backups").mkdir()
    (root / "config/platform.env").write_text(
        "DATABASE_URL='postgres://fixture:private@localhost/fixture_test'\nREDIS_URL='redis://:private@localhost/1'\nCUSTOM_FUTURE_FIELD=keep\n"
    )
    (root / "config/ai-settings.json").write_text(
        json.dumps(
            {
                "data_dir": str(root / "data/ai"),
                "api_key": "PRIVATE_MODEL_KEY",
                "host": "https://dashscope.aliyuncs.com",
                "admin_token": "PRIVATE_ADMIN",
                "client_token": "PRIVATE_APP",
            }
        )
    )
    (root / "config/Caddyfile").write_text(
        'localhost {\n reverse_proxy localhost:8090\n header Authorization "Bearer PRIVATE_HEADER"\n}'
    )
    sqlite3.connect(root / "data/ai/state.sqlite3").close()
    return root


def test_config_redaction_version_and_rollback(runtime, tmp_path, monkeypatch):
    data = ops.config_read(runtime)
    encoded = json.dumps(data)
    assert "PRIVATE_" not in encoded and "private@" not in encoded
    monkeypatch.setattr(ops, "run", lambda *a, **kw: b"")
    response = ops.dispatch(
        runtime,
        tmp_path,
        "write-config",
        {
            "expected_version": data["version"],
            "platform": {"DB_POOL_SIZE": "20"},
            "ai": {"api_key": ""},
        },
    )
    assert response["restart_required"]
    assert (
        ops.file_environment(runtime / "config/platform.env")["CUSTOM_FUTURE_FIELD"]
        == "keep"
    )
    assert (
        json.loads((runtime / "config/ai-settings.json").read_text())["api_key"]
        == "PRIVATE_MODEL_KEY"
    )
    with pytest.raises(ValueError):
        ops.dispatch(
            runtime, tmp_path, "write-config", {"expected_version": data["version"]}
        )
    before = ops.config_version(runtime)
    original_atomic = ops.atomic

    def fail(path, data):
        if path == runtime / "config/ai-settings.json":
            raise OSError("fixture disk failure")
        original_atomic(path, data)

    monkeypatch.setattr(ops, "atomic", fail)
    with pytest.raises(OSError):
        ops.dispatch(
            runtime,
            tmp_path,
            "write-config",
            {"expected_version": before, "platform": {"DB_POOL_SIZE": "30"}},
        )
    assert ops.config_version(runtime) == before


def test_library_paths_versions_and_recycle(runtime, tmp_path):
    for value in ("../config/platform.env", "/etc/passwd", "a/../../outside"):
        with pytest.raises(ValueError):
            ops.safe(runtime, value, exists=False)
    (runtime / "data/link").symlink_to(runtime / "config")
    with pytest.raises(ValueError):
        ops.safe(runtime, "data/link/platform.env")
    prepared = ops.dispatch(runtime, tmp_path, "prepare-upload", {"name": "角色.glb"})
    target = Path(prepared["path"])
    target.write_bytes(b"fakeGLB")
    row = ops.dispatch(
        runtime,
        tmp_path,
        "finish-upload",
        {"id": prepared["id"], "bytes": 7, "sha256": ops.sha(target)},
    )
    row = ops.dispatch(
        runtime,
        tmp_path,
        "write-library",
        {
            "id": row["id"],
            "operation": "metadata",
            "expected_version": 1,
            "description": "fixture",
        },
    )
    assert row["version"] == 2
    with pytest.raises(ValueError):
        ops.dispatch(
            runtime,
            tmp_path,
            "write-library",
            {"id": row["id"], "operation": "metadata", "expected_version": 1},
        )
    ops.dispatch(
        runtime, tmp_path, "write-library", {"id": row["id"], "operation": "delete"}
    )
    assert not ops.dispatch(runtime, tmp_path, "read-library", {})["items"]
    assert ops.dispatch(runtime, tmp_path, "read-library", {"folder": "trash"})[
        "items"
    ][0]["quarantined"]
    ops.dispatch(
        runtime, tmp_path, "write-library", {"id": row["id"], "operation": "restore"}
    )
    assert ops.dispatch(runtime, tmp_path, "read-library", {})["items"][0][
        "sha256"
    ] == ops.sha(target)


def test_jobs_are_independent_of_admin_service(runtime, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(ops, "run", lambda args, **kw: calls.append(args) or b"")
    result = ops.queue(runtime, tmp_path, "backup", {})
    assert (
        calls[0][0] == "systemd-run"
        and "--user" in calls[0]
        and "--collect" in calls[0]
    )
    assert "starry-admin-task-" + result["job_id"] in " ".join(calls[0])
    assert (
        ops.dispatch(runtime, tmp_path, "read-jobs", {})["items"][0]["state"]
        == "queued"
    )


@pytest.mark.skipif(
    os.environ.get("STARRY_INTEGRATION") != "1",
    reason="real isolated PostgreSQL required",
)
def test_backup_candidate_preserves_admin_and_revokes_sessions(
    runtime, tmp_path, monkeypatch
):
    from urllib.parse import urlsplit, urlunsplit

    source = os.environ["TEST_DATABASE_URL"]
    u = urlsplit(source)
    assert u.path.endswith("_test")
    db = "starry_backup_" + uuid.uuid4().hex[:8] + "_test"
    candidate = "starry_candidate_" + uuid.uuid4().hex[:8] + "_test"
    env = os.environ | {"DATABASE_URL": urlunsplit(u._replace(path="/" + db))}
    pg = ops.pg_environment(env)
    (runtime / "postgres").mkdir()
    (runtime / "postgres/bin").symlink_to("/opt/homebrew/opt/postgresql@17/bin")
    release = tmp_path / "release"
    (release / "bin").mkdir(parents=True)
    repo = DEPLOY.parents[1]
    wrapper = release / "bin/starry-migrate"
    wrapper.write_text(
        "#!/bin/sh\ncd " + shlex.quote(str(repo)) + "\nexec go run ./cmd/migrate\n"
    )
    wrapper.chmod(0o700)
    ops.run([runtime / "postgres/bin/createdb", db], env=pg, timeout=15)
    monkeypatch.setattr(ops, "service", lambda *a: None)
    monkeypatch.setattr(ops, "ready", lambda *a: None)

    def sql(query, database=db):
        return (
            ops.run(
                [
                    runtime / "postgres/bin/psql",
                    "-Atq",
                    "-v",
                    "ON_ERROR_STOP=1",
                    "-c",
                    query,
                ],
                env=ops.pg_environment(env, database),
                timeout=15,
            )
            .decode()
            .strip()
        )

    try:
        ops.run([wrapper], env=env, timeout=30)
        ops.env_write(
            runtime / "config/platform.env", {"DATABASE_URL": env["DATABASE_URL"]}
        )
        owner, user = uuid.uuid4(), uuid.uuid4()
        sql(
            f"INSERT INTO admin_users(id,username,password_hash,role) VALUES('{owner}','fixture_owner','test-hash','owner'); INSERT INTO users(id,username,password_hash) VALUES('{user}','fixture_user','test-hash')"
        )
        (runtime / "data/ai/audio/a.pcm").write_bytes(bytes(200))
        (runtime / "data/ai/admin-settings.json").write_text(
            '{"suggestions_model":"fixture"}'
        )
        backup = ops.create_backup(runtime, release)
        folder = runtime / "backups" / backup["id"]
        assert ops.verify_backup(runtime, backup["id"])["schema"] == 1
        sql(
            f"UPDATE users SET session_epoch=25 WHERE id='{user}';UPDATE admin_users SET username='owner_current' WHERE id='{owner}';SELECT setval('starry_registration_sequence',99,true)"
        )
        ops.restore_candidate(runtime, release, folder, candidate)
        assert sql("SELECT username FROM admin_users", candidate) == "owner_current"
        assert (
            sql(f"SELECT session_epoch FROM users WHERE id='{user}'", candidate) == "26"
        )
        assert (
            sql("SELECT last_value FROM starry_registration_sequence", candidate)
            == "99"
        )
        with tarfile.open(folder / "media.tar.gz") as archive:
            assert "ai/admin-settings.json" in archive.getnames()
        (folder / "media.tar.gz").write_bytes(b"tampered")
        with pytest.raises(ValueError):
            ops.verify_backup(runtime, backup["id"])
    finally:
        for name in (candidate, db):
            ops.run(
                [runtime / "postgres/bin/dropdb", "--if-exists", "--force", name],
                env=pg,
                timeout=15,
            )


@pytest.mark.skipif(
    os.environ.get("STARRY_INTEGRATION") != "1",
    reason="real isolated PostgreSQL required",
)
def test_full_restore_and_failed_readiness_rollback(runtime, tmp_path, monkeypatch):
    import re
    from urllib.parse import urlsplit, urlunsplit

    source = os.environ["TEST_DATABASE_URL"]
    u = urlsplit(source)
    assert u.path.endswith("_test")
    db = "starry_switch_" + uuid.uuid4().hex[:8] + "_test"
    env = os.environ | {"DATABASE_URL": urlunsplit(u._replace(path="/" + db))}
    pg = ops.pg_environment(env)
    (runtime / "postgres").mkdir()
    (runtime / "postgres/bin").symlink_to("/opt/homebrew/opt/postgresql@17/bin")
    release = tmp_path / "release"
    (release / "bin").mkdir(parents=True)
    wrapper = release / "bin/starry-migrate"
    wrapper.write_text(
        "#!/bin/sh\ncd "
        + shlex.quote(str(DEPLOY.parents[1]))
        + "\nexec go run ./cmd/migrate\n"
    )
    wrapper.chmod(0o700)
    real_run = ops.run
    databases = {db}

    def tracked(args, **kw):
        if Path(args[0]).name == "createdb":
            databases.add(str(args[1]))
        for arg in args:
            if isinstance(arg, str) and "ALTER DATABASE" in arg:
                databases.update(re.findall(r'"([a-zA-Z0-9_]+)"', arg))
        return real_run(args, **kw)

    monkeypatch.setattr(ops, "run", tracked)
    monkeypatch.setattr(ops, "service", lambda *a: None)
    monkeypatch.setattr(ops, "ready", lambda *a: None)

    def sql(query):
        return (
            ops.run(
                [
                    runtime / "postgres/bin/psql",
                    "-Atq",
                    "-v",
                    "ON_ERROR_STOP=1",
                    "-c",
                    query,
                ],
                env=pg,
                timeout=15,
            )
            .decode()
            .strip()
        )

    try:
        ops.run([runtime / "postgres/bin/createdb", db], env=pg, timeout=15)
        ops.run([wrapper], env=env, timeout=30)
        ops.env_write(
            runtime / "config/platform.env", {"DATABASE_URL": env["DATABASE_URL"]}
        )
        owner, user = uuid.uuid4(), uuid.uuid4()
        sql(
            f"INSERT INTO admin_users(id,username,password_hash,role) VALUES('{owner}','restore_owner','test-hash','owner');INSERT INTO users(id,username,password_hash,profile) VALUES('{user}','restore_user','test-hash','{{\"marker\":\"backup\"}}')"
        )
        audio = runtime / "data/ai/audio/a.pcm"
        audio.write_bytes(b"backup sound")
        backup = ops.create_backup(runtime, release)
        sql('UPDATE users SET profile=\'{"marker":"current"}\',session_epoch=40')
        audio.write_bytes(b"current sound")
        job = runtime / "data/admin/jobs/test.json"
        ops.atomic(job, dict(state="running"))
        raised = [False]

        def readiness(*a):
            if (
                sql("SELECT profile->>'marker' FROM users") == "backup"
                and not raised[0]
            ):
                raised[0] = True
                raise ValueError("fixture readiness failure")

        monkeypatch.setattr(ops, "ready", readiness)
        with pytest.raises(ValueError):
            ops.restore_backup(runtime, release, backup["id"], job)
        assert raised[0] and sql("SELECT profile->>'marker' FROM users") == "current"
        assert audio.read_bytes() == b"current sound"
        monkeypatch.setattr(ops, "ready", lambda *a: None)
        result = ops.restore_backup(runtime, release, backup["id"], job)
        assert (
            result["sessions_revoked"]
            and sql("SELECT profile->>'marker' FROM users") == "backup"
        )
        assert (
            sql("SELECT session_epoch FROM users") == "41"
            and audio.read_bytes() == b"backup sound"
        )
    finally:
        for name in databases:
            assert re.fullmatch(r"[a-zA-Z0-9_]+", name)
            real_run(
                [runtime / "postgres/bin/dropdb", "--if-exists", "--force", name],
                env=pg,
                timeout=15,
            )
