"""Sarovi music responses become playable job music without exposing the key."""
import base64
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from brain import sarovi_music


def test_sarovi_clip_request_and_response(monkeypatch):
    monkeypatch.setenv("SAROVI_API_KEY", "private-test-key")
    seen = {}

    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): return False

    def fake_open(request, timeout):
        seen["url"] = request.full_url
        seen["body"] = json.loads(request.data)
        seen["authorization"] = request.get_header("Authorization")
        seen["timeout"] = timeout
        return Response()

    monkeypatch.setattr(sarovi_music.urllib.request, "urlopen", fake_open)
    monkeypatch.setattr(sarovi_music.json, "load", lambda _: {
        "output": {"data": base64.b64encode(b"mp3-data").decode(), "mediaType": "audio/mpeg"}
    })
    assert sarovi_music.generate_clip("Calm instrumental, no vocals") == b"mp3-data"
    assert seen == {
        "url": sarovi_music.ENDPOINT,
        "body": {"model": sarovi_music.MODEL, "text": "Calm instrumental, no vocals", "format": "mp3"},
        "authorization": "Bearer private-test-key",
        "timeout": 300,
    }


def test_generate_route_saves_clip_for_preview(tmp_path, monkeypatch):
    from app.routers import music
    monkeypatch.setattr("app.jobs.get", lambda _: SimpleNamespace(dir=tmp_path))
    monkeypatch.setattr("app.jobs._write_status", lambda _: None)
    monkeypatch.setattr(sarovi_music, "generate_clip", lambda _: b"valid-audio")
    monkeypatch.setattr("engine.probe.probe", lambda _: {
        "streams": [{"codec_type": "audio"}], "format": {"duration": "30.0"}
    })
    app = FastAPI()
    app.include_router(music.router)
    with TestClient(app) as client:
        response = client.post("/jobs/example/music/generate", json={"prompt": "Calm instrumental"})
        assert response.status_code == 200
        path = response.json()["path"]
        assert path.startswith("music/sarovi_lyria_")
        assert (tmp_path / path).read_bytes() == b"valid-audio"
        assert client.get("/jobs/example/music/preview", params={"filename": Path(path).name}).content == b"valid-audio"
