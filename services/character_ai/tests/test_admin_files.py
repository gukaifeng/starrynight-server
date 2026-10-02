import io, wave
import httpx, pytest
from services.character_ai.app import create_app
from services.character_ai.config import Settings


@pytest.mark.asyncio
async def test_existing_audio_and_nested_models_can_be_inspected_and_recovered(
    tmp_path,
):
    app = create_app(
        Settings(data_dir=tmp_path, admin_token="private-fixture", paid_enabled=False)
    )
    headers = {"Authorization": "Bearer private-fixture"}
    (tmp_path / "audio").mkdir(exist_ok=True)
    (tmp_path / "audio/a.pcm").write_bytes(bytes(4800))
    (tmp_path / "models/nested").mkdir(parents=True, exist_ok=True)
    (tmp_path / "models/nested/weights.onnx").write_bytes(b"fixture")
    (tmp_path / "audio/link.pcm").symlink_to(tmp_path / "state.sqlite3")
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            root = "/v1/admin/console/files"
            assert (await client.get(root)).status_code == 401
            listing = (await client.get(root, headers=headers)).json()
            assert len(listing["items"]) == 1
            row = listing["items"][0]
            result = await client.get(
                root + "/download", params={"id": row["id"]}, headers=headers
            )
            assert result.status_code == 200
            with wave.open(io.BytesIO(result.content)) as wav:
                assert wav.getframerate() == 24000 and wav.getnframes() == 2400
            for id in (
                "audio/../state.sqlite3",
                "audio/link.pcm",
                "/state.sqlite3",
                "models/../../state.sqlite3",
            ):
                assert (
                    await client.get(
                        root + "/download", params={"id": id}, headers=headers
                    )
                ).status_code in (404, 422)
            model = (
                await client.get(root, params={"group": "models"}, headers=headers)
            ).json()["items"][0]
            assert model["id"] == "models/nested/weights.onnx"
            assert (
                await client.post(
                    root + "/delete",
                    json={
                        "id": model["id"],
                        "version": model["version"],
                        "confirmed": True,
                    },
                    headers=headers,
                )
            ).status_code == 403
            assert (
                await client.post(
                    root + "/delete",
                    json={"id": row["id"], "version": "stale", "confirmed": True},
                    headers=headers,
                )
            ).status_code == 409
            assert (
                await client.post(
                    root + "/delete",
                    json={
                        "id": row["id"],
                        "version": row["version"],
                        "confirmed": True,
                    },
                    headers=headers,
                )
            ).status_code == 200
            trash = (
                await client.get(root, params={"group": "trash"}, headers=headers)
            ).json()["items"][0]
            assert trash["original"] == row["id"]
            response = await client.post(
                root + "/delete",
                json={
                    "id": trash["id"],
                    "version": trash["version"],
                    "action": "restore",
                    "confirmed": True,
                },
                headers=headers,
            )
            assert response.status_code == 200
            assert (tmp_path / "audio/a.pcm").exists()
            assert (
                await client.get(root, params={"group": "trash"}, headers=headers)
            ).json()["items"] == []
            assert not app.state.store.db.execute("SELECT * FROM usage").fetchall()
    finally:
        app.state.store.db.close()
        await app.state.engine.provider.close()
