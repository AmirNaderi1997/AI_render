"""Provider-neutral media generation adapter with registry and local fixture provider."""
from __future__ import annotations

import hashlib
import io
import logging
import math
import os
import random
import subprocess
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class MediaResult:
    file_path: str
    source: str
    cost_usd: Optional[float] = 0.0
    metadata: dict = field(default_factory=dict)
    generation_id: str = ""
    width: int = 0
    height: int = 0
    duration_s: float = 0.0
    fps: int = 0


class ProviderAdapter(ABC):
    name: str = "base"

    @abstractmethod
    def generate_image(self, prompt: str, aspect: str, output_dir: Path) -> MediaResult:
        ...

    @abstractmethod
    def generate_video(self, prompt: str, duration: float, aspect: str, output_dir: Path) -> MediaResult:
        ...

    @property
    def capabilities(self) -> list[str]:
        return ["image", "video"]

    @property
    def has_key(self) -> bool:
        key_var = f"CONTENT_PROVIDER_{self.name.upper()}_KEY"
        return bool(os.environ.get(key_var))


def _retry_with_backoff(fn, max_retries: int = 3):
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as exc:
            if attempt == max_retries - 1:
                raise
            wait = (2 ** attempt) + random.uniform(0, 1)
            log.warning("attempt %d failed (%s), retrying in %.1fs", attempt + 1, exc, wait)
            time.sleep(wait)


def _parse_resolution(aspect: str) -> tuple[int, int]:
    mapping = {
        "9:16": (1080, 1920),
        "1:1": (1080, 1080),
        "16:9": (1920, 1080),
        "4:5": (1080, 1350),
    }
    return mapping.get(aspect, (1080, 1920))


def still_to_motion_video(
    image_path: Path,
    output_dir: Path,
    duration: float,
    aspect: str,
    *,
    generation_id: str = "",
    cost_usd: Optional[float] = 0.0,
    source: str = "image_motion",
    metadata: Optional[dict] = None,
) -> MediaResult:
    """Turn a generated still into a bounded, editable H.264 timeline source."""
    if not isinstance(duration, (int, float)) or isinstance(duration, bool) \
            or not math.isfinite(duration) or duration <= 0:
        raise ValueError("video duration must be a positive finite number")
    still = Path(image_path)
    if not still.is_file():
        raise FileNotFoundError(f"image source not found: {still}")
    duration_s = min(float(duration), 30.0)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    generation_id = generation_id or uuid.uuid4().hex[:12]
    width, height = _parse_resolution(aspect)
    fps = 30
    frames = max(1, round(duration_s * fps))
    out_path = output_dir / f"motion_{generation_id}.mp4"
    zoom_filter = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},"
        f"zoompan=z='min(1+0.0002*on,1.08)':"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d={frames}:s={width}x{height}:fps={fps},format=yuv420p"
    )
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-i", str(still),
        "-vf", zoom_filter, "-frames:v", str(frames),
        "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-movflags", "+faststart", str(out_path),
    ], capture_output=True, check=True, timeout=max(60, round(duration_s * 12)))
    return MediaResult(
        file_path=str(out_path),
        source=source,
        cost_usd=cost_usd,
        generation_id=generation_id,
        width=width,
        height=height,
        duration_s=round(frames / fps, 3),
        fps=fps,
        metadata={**(metadata or {}), "still_path": str(still), "motion": "subtle_zoompan"},
    )


class LocalFixtureProvider(ProviderAdapter):
    """Generates placeholder colored frames/video with ffmpeg. No API keys needed."""

    name = "local_fixture"

    @property
    def has_key(self) -> bool:
        return True

    def generate_image(self, prompt: str, aspect: str, output_dir: Path) -> MediaResult:
        w, h = _parse_resolution(aspect)
        gen_id = uuid.uuid4().hex[:12]
        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / f"fixture_{gen_id}.png"

        color = "#{:06x}".format(random.randint(0x222222, 0xCCCCCC))
        label = prompt[:40].replace("'", "").replace('"', "")

        def _gen():
            subprocess.run([
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", f"color=c={color}:s={w}x{h}:d=1",
                "-vf", f"drawtext=text='{label}':fontsize=36:fontcolor=white:x=(w-tw)/2:y=(h-th)/2",
                "-frames:v", "1",
                str(out_path),
            ], capture_output=True, check=True, timeout=15)

        try:
            _retry_with_backoff(_gen, max_retries=2)
        except Exception:
            subprocess.run([
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", f"color=c={color}:s={w}x{h}:d=1",
                "-frames:v", "1",
                str(out_path),
            ], capture_output=True, check=True, timeout=15)

        return MediaResult(
            file_path=str(out_path),
            source="local_fixture",
            cost_usd=0.0,
            generation_id=gen_id,
            width=w, height=h,
            duration_s=0.0, fps=0,
            metadata={"prompt": prompt, "color": color},
        )

    def generate_video(self, prompt: str, duration: float, aspect: str, output_dir: Path) -> MediaResult:
        w, h = _parse_resolution(aspect)
        gen_id = uuid.uuid4().hex[:12]
        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / f"fixture_{gen_id}.mp4"
        fps = 30

        color = "#{:06x}".format(random.randint(0x222222, 0xCCCCCC))
        dur = max(0.5, min(duration, 30.0))

        def _gen():
            subprocess.run([
                "ffmpeg", "-y",
                "-f", "lavfi", "-i",
                f"color=c={color}:s={w}x{h}:d={dur}:r={fps}",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-t", str(dur),
                str(out_path),
            ], capture_output=True, check=True, timeout=60)

        _retry_with_backoff(_gen, max_retries=3)

        return MediaResult(
            file_path=str(out_path),
            source="local_fixture",
            cost_usd=0.0,
            generation_id=gen_id,
            width=w,
            height=h,
            duration_s=round(dur, 2),
            fps=fps,
            metadata={"prompt": prompt, "color": color},
        )


class JarvisImageProvider(ProviderAdapter):
    """Generate stills with the configured OpenAI-compatible image endpoint.

    Reels and Stories use those generated stills as short, gently animated
    clips. This keeps the feature usable when no dedicated video model is
    configured and records the provider's image cost as unknown when its API
    response does not include billing data.
    """

    name = "jarvis_image"

    @property
    def capabilities(self) -> list[str]:
        return ["image", "motion_video_from_image"]

    @property
    def has_key(self) -> bool:
        return bool(
            os.environ.get("IMAGE_API_KEY")
            or os.environ.get("JARVIS_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
        )

    @staticmethod
    def _client_config() -> tuple[str, Optional[str], str]:
        api_key = (os.environ.get("IMAGE_API_KEY") or os.environ.get("JARVIS_API_KEY")
                   or os.environ.get("OPENAI_API_KEY") or "")
        if not api_key:
            raise RuntimeError("Set IMAGE_API_KEY, JARVIS_API_KEY, or OPENAI_API_KEY to use jarvis_image")

        base_url = (os.environ.get("IMAGE_BASE_URL") or os.environ.get("JARVIS_BASE_URL")
                    or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        if base_url.endswith("/images"):
            base_url = base_url[:-len("/images")]
        model = os.environ.get("IMAGE_MODEL", "").strip()
        if not model:
            raise RuntimeError("IMAGE_MODEL is not configured for jarvis_image")
        return api_key, base_url, model

    def generate_image(self, prompt: str, aspect: str, output_dir: Path) -> MediaResult:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("image prompt must not be empty")
        output_dir.mkdir(parents=True, exist_ok=True)
        api_key, base_url, model = self._client_config()

        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=180, max_retries=0)
        aspect_note = {
            "9:16": (
                "Create one continuous photograph composed for a central vertical 9:16 crop "
                "from this square image. Keep every essential face, hand, and action within "
                "the middle 55% of the image width. No side panels, borders, or seams."
            ),
            "4:5": "Compose for a portrait 4:5 crop, keeping the main subject near the center.",
            "1:1": "Compose for a square 1:1 frame.",
            "16:9": "Compose for a wide 16:9 crop, keeping the main subject near the center.",
        }.get(aspect, "Keep the main subject centered with safe space around it.")
        request_prompt = (
            f"{prompt.strip()}\n\n{aspect_note} Do not add captions, lettering, "
            "logos, or legible text on paper, clothing, signs, or screens."
        )
        fallback_model = os.environ.get("IMAGE_FALLBACK_MODEL", "").strip()
        if not fallback_model and "api.jarvis.you" in base_url:
            fallback_model = "gemini-3-1-flash-image"
        try:
            response = client.images.generate(
                model=model, prompt=request_prompt, size="1024x1024", n=1,
            )
            selected_model = model
        except Exception as exc:
            status_code = getattr(exc, "status_code", None)
            recoverable = isinstance(status_code, int) and status_code >= 500
            if not recoverable or not fallback_model or fallback_model == model:
                raise
            log.warning(
                "image model %s failed with %s; retrying once with %s",
                model, f"HTTP {status_code}" if status_code else type(exc).__name__,
                fallback_model,
            )
            response = client.images.generate(
                model=fallback_model, prompt=request_prompt, size="1024x1024", n=1,
            )
            selected_model = fallback_model
        entries = getattr(response, "data", None) or []
        entry = entries[0] if entries else None
        encoded = getattr(entry, "b64_json", None) if entry is not None else None
        if isinstance(entry, dict):
            encoded = entry.get("b64_json")
        if not isinstance(encoded, str) or not encoded:
            raise RuntimeError("image provider returned no base64 image data")

        import base64
        try:
            image_bytes = base64.b64decode(encoded, validate=True)
            from PIL import Image
            image = Image.open(io.BytesIO(image_bytes))
            image.load()
            width, height = image.size
            out_path = output_dir / f"jarvis_{uuid.uuid4().hex[:12]}.png"
            image.convert("RGB").save(out_path, format="PNG")
        except Exception as exc:
            raise RuntimeError(f"image provider returned an invalid image: {exc}") from exc

        return MediaResult(
            file_path=str(out_path),
            source="jarvis_image",
            cost_usd=None,
            generation_id=out_path.stem.removeprefix("jarvis_"),
            width=width,
            height=height,
            metadata={"prompt": prompt, "model": selected_model,
                      "requested_model": model, "fallback_used": selected_model != model,
                      "aspect": aspect, "billing_reported": False},
        )

    def generate_video(self, prompt: str, duration: float, aspect: str,
                       output_dir: Path) -> MediaResult:
        still = self.generate_image(prompt, aspect, output_dir)
        return still_to_motion_video(
            still.file_path, output_dir, duration, aspect,
            generation_id=still.generation_id, cost_usd=still.cost_usd,
            source="jarvis_image_motion", metadata=still.metadata,
        )


class SaroviImageProvider(ProviderAdapter):
    """Generate editable content stills with a selected Sarovi image model."""

    def __init__(self, name: str, model: str):
        self.name = name
        self.model = model

    @property
    def capabilities(self) -> list[str]:
        return ["image", "motion_video_from_image"]

    @property
    def has_key(self) -> bool:
        return bool(os.getenv("SAROVI_API_KEY", "").strip())

    def generate_image(self, prompt: str, aspect: str, output_dir: Path) -> MediaResult:
        import base64
        import binascii
        from PIL import Image
        from .sarovi import request

        if not isinstance(prompt, str) or len(prompt.strip()) < 3:
            raise ValueError("image prompt must contain at least three characters")
        if aspect not in ("9:16", "1:1", "16:9", "4:5"):
            raise ValueError("unsupported image aspect ratio")
        request_prompt = (
            prompt.strip() + "\nDo not add captions, lettering, logos, or legible text; "
            "the caption layer is rendered separately."
        )
        if len(request_prompt) > 8000:
            raise ValueError("image prompt exceeds Sarovi's 8000-character limit")
        payload = {
            "model": self.model, "prompt": request_prompt,
            "aspectRatio": aspect, "count": 1,
            "quality": "medium", "outputFormat": "png",
        }
        selected_model = self.model
        try:
            result = request("/studio/image", payload)
        except RuntimeError as exc:
            # The advertised Seedream route currently returns this upstream error
            # for even the catalog's minimal request. Preserve the requested model
            # in metadata while keeping image generation usable.
            if self.name != "sarovi_seedream" or "HTTP 502: INVALID_REFERENCE" not in str(exc):
                raise
            selected_model = "google/gemini-2.5-flash-image"
            log.warning("Sarovi Seedream returned INVALID_REFERENCE; trying Nano Banana")
            result = request("/studio/image", {**payload, "model": selected_model})
        outputs = result.get("outputs") or []
        item = outputs[0] if outputs else None
        if not isinstance(item, dict) or item.get("mediaType") not in ("image/png", "image/jpeg", "image/webp"):
            raise RuntimeError("Sarovi returned no supported image")
        encoded = item.get("data")
        if not isinstance(encoded, str):
            raise RuntimeError("Sarovi returned no image data")
        try:
            raw = base64.b64decode(encoded, validate=True)
            if len(raw) > 30 * 1024 * 1024:
                raise ValueError("image is too large")
            image = Image.open(io.BytesIO(raw))
            image.load()
            width, height = image.size
        except (ValueError, binascii.Error, OSError) as exc:
            raise RuntimeError("Sarovi returned invalid image data") from exc
        output_dir.mkdir(parents=True, exist_ok=True)
        gen_id = uuid.uuid4().hex[:12]
        out_path = output_dir / f"{self.name}_{gen_id}.png"
        image.convert("RGB").save(out_path, format="PNG")
        return MediaResult(
            file_path=str(out_path), source=self.name, cost_usd=None,
            generation_id=gen_id, width=width, height=height,
            metadata={"prompt": prompt, "model": selected_model,
                      "requested_model": self.model, "fallback_used": selected_model != self.model,
                      "aspect": aspect,
                      "billing_reported": False, "sarovi_generation_id": result.get("generationId")},
        )

    def generate_video(self, prompt: str, duration: float, aspect: str,
                       output_dir: Path) -> MediaResult:
        still = self.generate_image(prompt, aspect, output_dir)
        return still_to_motion_video(
            still.file_path, output_dir, duration, aspect,
            generation_id=still.generation_id, cost_usd=still.cost_usd,
            source=f"{self.name}_motion", metadata=still.metadata,
        )

_registry: dict[str, ProviderAdapter] = {}


def register_provider(name: str, adapter: ProviderAdapter) -> None:
    adapter.name = name
    _registry[name] = adapter


def get_provider(name: str) -> ProviderAdapter:
    if name not in _registry:
        raise KeyError(f"unknown provider: {name!r}. registered: {list(_registry.keys())}")
    return _registry[name]


def list_providers() -> list[dict]:
    return [
        {"name": name, "capabilities": adapter.capabilities,
         "has_key": adapter.has_key, "key_configured": adapter.has_key}
        for name, adapter in _registry.items()
    ]


register_provider("local_fixture", LocalFixtureProvider())
register_provider("jarvis_image", JarvisImageProvider())
register_provider("sarovi_seedream", SaroviImageProvider(
    "sarovi_seedream", "bytedance-seed/seedream-5-0-lite"))
register_provider("sarovi_nano_banana", SaroviImageProvider(
    "sarovi_nano_banana", "google/gemini-2.5-flash-image"))
