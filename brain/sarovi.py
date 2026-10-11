"""Small server-side client for Sarovi's public v1 contract."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

BASE_URL = "https://api.sarovi.ir/v1"


def response_output_text(result: dict) -> str:
    """Return text from either supported Responses API response shape."""
    direct = result.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()

    parts: list[str] = []
    for output in result.get("output") or []:
        if not isinstance(output, dict):
            continue
        for content in output.get("content") or []:
            if not isinstance(content, dict) or content.get("type") != "output_text":
                continue
            text = content.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
    return "\n".join(parts)


def request(path: str, payload: dict, *, timeout: float = 300) -> dict:
    key = os.getenv("SAROVI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("SAROVI_API_KEY is not configured")
    req = urllib.request.Request(
        BASE_URL + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            code = json.load(exc).get("error", {}).get("code", "UNKNOWN")
        except (ValueError, AttributeError):
            code = "UNKNOWN"
        raise RuntimeError(f"Sarovi request failed (HTTP {exc.code}: {code})") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("Sarovi request could not connect") from exc
    if not isinstance(result, dict):
        raise RuntimeError("Sarovi returned an invalid response")
    return result
