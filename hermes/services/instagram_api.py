"""Instagram Login API wrapper with a per-user rolling quota and bounded retries."""
import asyncio
import hashlib
import random
import time
from collections import defaultdict, deque

import httpx

from hermes.config import instagram_credentials, settings


class InstagramError(Exception):
    def __init__(self, code, status=502):
        self.code, self.status = code, status
        super().__init__(code)


_local_calls = defaultdict(deque)
_quota_lock = asyncio.Lock()
_redis = None


async def _reserve(user_id):
    global _redis
    key = "hermes:igquota:" + hashlib.sha256(str(user_id).encode()).hexdigest()
    if settings.REDIS_URL:
        try:
            import redis.asyncio as redis
            if _redis is None:
                _redis = redis.from_url(settings.REDIS_URL)
            now = time.time()
            count = await _redis.eval(
                "redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, ARGV[1]-3600); "
                "if redis.call('ZCARD', KEYS[1]) >= 200 then return 0 end; "
                "redis.call('ZADD', KEYS[1], ARGV[1], ARGV[2]); "
                "redis.call('EXPIRE', KEYS[1], 3600); return 1",
                1, key, now, f"{now}:{random.random()}")
            if count == 0:
                raise InstagramError("INSTAGRAM_RATE_LIMIT", 429)
            return
        except InstagramError:
            raise
        except Exception as exc:
            raise InstagramError("INSTAGRAM_RATE_LIMITER_UNAVAILABLE", 503) from exc
    async with _quota_lock:
        calls = _local_calls[key]
        now = time.monotonic()
        while calls and calls[0] <= now - 3600:
            calls.popleft()
        if len(calls) >= 200:
            raise InstagramError("INSTAGRAM_RATE_LIMIT", 429)
        calls.append(now)


class InstagramAPI:
    def __init__(self, user_id, token=None):
        self.user_id = user_id
        self.token = token
        self.base = f"https://graph.instagram.com/{settings.INSTAGRAM_GRAPH_VERSION}"

    async def request(self, method, url, *, data=None, params=None, token=None):
        auth = token if token is not None else self.token
        headers = {"Authorization": f"Bearer {auth}"} if auth else {}
        for attempt in range(5):
            await _reserve(self.user_id)
            try:
                async with httpx.AsyncClient(timeout=20) as client:
                    response = await client.request(method, url, data=data, params=params, headers=headers)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt == 4:
                    raise InstagramError("INSTAGRAM_UNAVAILABLE") from exc
                await asyncio.sleep(min(2 ** attempt, 8))
                continue
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            graph_code = payload.get("error", {}).get("code") if isinstance(payload, dict) else None
            limited = response.status_code == 429 or graph_code in (4, 17, 32, 613)
            if limited or response.status_code >= 500:
                if attempt == 4:
                    raise InstagramError("INSTAGRAM_RATE_LIMIT" if limited else "INSTAGRAM_UNAVAILABLE", 429 if limited else 502)
                try:
                    retry = float(response.headers.get("Retry-After", "0"))
                except ValueError:
                    retry = 0
                await asyncio.sleep(min(max(retry, 2 ** attempt + random.random()), 30))
                continue
            if response.status_code >= 400:
                auth_error = response.status_code in (401, 403) or graph_code == 190
                raise InstagramError("INSTAGRAM_AUTH_ERROR" if auth_error else "INSTAGRAM_API_ERROR", 502)
            if not isinstance(payload, dict):
                raise InstagramError("INSTAGRAM_INVALID_RESPONSE")
            return payload
        raise InstagramError("INSTAGRAM_UNAVAILABLE")

    async def exchange_code(self, code):
        credentials = await instagram_credentials(self.user_id)
        return await self.request("POST", "https://api.instagram.com/oauth/access_token", data={
            "client_id": credentials["app_id"],
            "client_secret": credentials["app_secret"],
            "grant_type": "authorization_code",
            "redirect_uri": settings.INSTAGRAM_REDIRECT_URI,
            "code": code,
        })

    async def long_lived_token(self, token):
        credentials = await instagram_credentials(self.user_id)
        return await self.request("GET", "https://graph.instagram.com/access_token", params={
            "grant_type": "ig_exchange_token", "client_secret": credentials["app_secret"],
            "access_token": token,
        })

    async def refresh_token(self, token):
        return await self.request("GET", "https://graph.instagram.com/refresh_access_token", params={
            "grant_type": "ig_refresh_token", "access_token": token,
        })

    async def profile(self):
        return await self.request("GET", f"{self.base}/me", params={"fields": "id,username,followers_count,follows_count"})

    async def create_container(self, ig_user_id, media_url, caption, *, carousel=False):
        data = {"image_url": media_url}
        if media_url.lower().split("?")[0].endswith((".mp4", ".mov")):
            data = {"video_url": media_url, "media_type": "REELS"}
        if carousel:
            data["is_carousel_item"] = "true"
            if "video_url" in data:
                data["media_type"] = "VIDEO"
        else:
            data["caption"] = caption
        return await self.request("POST", f"{self.base}/{ig_user_id}/media", data=data)

    async def container_status(self, container_id):
        return await self.request("GET", f"{self.base}/{container_id}", params={"fields": "status_code"})

    async def publish(self, ig_user_id, media_urls, caption):
        if not media_urls:
            raise InstagramError("MEDIA_REQUIRED", 422)
        if len(media_urls) > 10:
            raise InstagramError("TOO_MANY_MEDIA", 422)
        carousel = len(media_urls) > 1
        ids = []
        for url in media_urls:
            response = await self.create_container(ig_user_id, url, caption, carousel=carousel)
            if not response.get("id"):
                raise InstagramError("INSTAGRAM_INVALID_RESPONSE")
            ids.append(response["id"])
        if carousel:
            response = await self.request("POST", f"{self.base}/{ig_user_id}/media", data={
                "media_type": "CAROUSEL", "children": ",".join(ids), "caption": caption})
            container_id = response.get("id")
        else:
            container_id = ids[0]
        if not container_id:
            raise InstagramError("INSTAGRAM_INVALID_RESPONSE")
        for _ in range(10):
            state = await self.container_status(container_id)
            if state.get("status_code") == "FINISHED":
                break
            if state.get("status_code") in ("ERROR", "EXPIRED"):
                raise InstagramError("MEDIA_PROCESSING_FAILED")
            await asyncio.sleep(3)
        else:
            raise InstagramError("MEDIA_PROCESSING_TIMEOUT")
        result = await self.request("POST", f"{self.base}/{ig_user_id}/media_publish", data={"creation_id": container_id})
        if not result.get("id"):
            raise InstagramError("INSTAGRAM_INVALID_RESPONSE")
        return result["id"]

    async def insights(self, object_id, metrics, *, period=None):
        values = {}
        for metric in metrics:
            params = {"metric": metric}
            if period:
                params["period"] = period
            try:
                response = await self.request("GET", f"{self.base}/{object_id}/insights", params=params)
            except InstagramError as exc:
                if exc.code == "INSTAGRAM_API_ERROR":
                    values[metric] = None  # unsupported metric for this media/account type
                    continue
                raise
            data = response.get("data") or []
            item = data[0] if data else {}
            values[metric] = item.get("total_value", {}).get("value") if "total_value" in item else (item.get("values") or [{}])[-1].get("value")
        return values
