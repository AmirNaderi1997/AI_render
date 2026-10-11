"""Content type presets for Instagram Reels, Posts, and Stories."""
from __future__ import annotations

from enum import Enum
from typing import Optional


class ContentType(str, Enum):
    REEL = "reel"
    POST = "post"
    STORY = "story"


_PRESETS: dict[ContentType, dict] = {
    ContentType.REEL: {
        "aspect": "9:16",
        "max_duration": 90,
        "max_scene_stretch": 1.15,
        "max_narration_speed": 1.15,
        "fps": 30,
        "resolution": "1080x1920",
        "width": 1080,
        "height": 1920,
        "is_static": False,
    },
    ContentType.POST: {
        "aspect": "1:1",
        "max_duration": None,
        "max_scene_stretch": 1.0,
        "max_narration_speed": 1.15,
        "fps": 30,
        "resolution": "1080x1080",
        "width": 1080,
        "height": 1080,
        "is_static": True,
    },
    ContentType.STORY: {
        "aspect": "9:16",
        "max_duration": 15,
        "max_scene_stretch": 1.15,
        "max_narration_speed": 1.15,
        "fps": 30,
        "resolution": "1080x1920",
        "width": 1080,
        "height": 1920,
        "is_static": False,
    },
}


def get_preset(content_type: ContentType | str) -> dict:
    if isinstance(content_type, str):
        content_type = ContentType(content_type)
    return dict(_PRESETS[content_type])
