from unittest.mock import AsyncMock

from hermes.database import _read
from hermes.services.instagram_api import InstagramAPI


def test_post_crud_publish_and_owner_scope(client, account, monkeypatch):
    body = {"account_id": account["id"], "caption": "Hello", "media_urls": ["https://example.com/a.jpg"]}
    response = client.post("/api/hermes/posts/", json=body)
    assert response.status_code == 200, response.text
    post_id = response.json()["id"]
    assert client.get("/api/hermes/posts/").json()[0]["id"] == post_id
    assert client.put(f"/api/hermes/posts/{post_id}", json={"caption": "Edited"}).json()["caption"] == "Edited"
    monkeypatch.setattr(InstagramAPI, "publish", AsyncMock(return_value="ig-post-1"))
    published = client.post(f"/api/hermes/posts/{post_id}/publish")
    assert published.status_code == 200, published.text
    assert published.json()["ig_post_id"] == "ig-post-1"
    assert client.post(f"/api/hermes/posts/{post_id}/publish").status_code == 409
    assert client.delete(f"/api/hermes/posts/{post_id}").status_code == 409
    assert client.get("/api/hermes/posts/no-such-post").status_code == 404


def test_post_rejects_foreign_account_and_nonpublic_media(client, account):
    assert client.post("/api/hermes/posts/", json={"account_id": "other"}).status_code == 404
    assert client.post("/api/hermes/posts/", json={"account_id": account["id"], "media_urls": ["http://localhost/a.jpg"]}).status_code == 422
    uploaded = client.post("/api/hermes/posts/media", files={"file": ("image.jpg", b"image", "image/jpeg")})
    assert uploaded.status_code == 200
    assert uploaded.json()["requires_public_url"] is True
