"""Tests for Content Creator feature: content_types, storyboard, media_provider, content_creator."""
from __future__ import annotations

import json
import base64
import io
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from engine.content_types import ContentType, get_preset
from brain.storyboard import Storyboard, Scene, generate_storyboard, _build_storyboard_system_prompt
from brain.ai_provider import JarvisProvider, LocalFallbackProvider
from brain.media_provider import (
    LocalFixtureProvider, JarvisImageProvider, register_provider, get_provider, list_providers,
    MediaResult, _registry,
)
from brain.content_creator import create_content, update_storyboard, storyboard_to_plan, _concat_audio, _run_generation, _fit_video_to_narration, _fit_post_narration, _fit_limited_narration
from engine.schema import EditPlan, validate_plan


# ── Helpers ──────────────────────────────────────────────────────────────────

def _storyboard_provider(response):
    provider = MagicMock()
    provider.generate_storyboard.return_value = response
    return provider


def _mock_storyboard_response(content_type: str = "reel"):
    if content_type == "post":
        return {
            "scenes": [{
                "index": 0,
                "description": "Product showcase on clean background",
                "duration_s": 5.0,
                "text_overlay": "New Collection",
                "media_method": "generate",
                "media_prompt": "elegant product photo on white background",
                "estimated_cost": 0.04,
            }],
        }
    if content_type == "story":
        return {
            "scenes": [
                {"index": 0, "description": "Attention grabber", "duration_s": 5.0,
                 "text_overlay": "Did you know?", "media_method": "generate",
                 "media_prompt": "bold text on gradient", "estimated_cost": 0.04},
                {"index": 1, "description": "Main message", "duration_s": 7.0,
                 "text_overlay": "Check this out", "media_method": "generate",
                 "media_prompt": "product in action", "estimated_cost": 0.05},
            ],
        }
    return {
        "scenes": [
            {"index": 0, "description": "Hook opening", "duration_s": 3.0,
             "text_overlay": "Welcome", "media_method": "generate",
             "media_prompt": "beautiful sunset over city", "estimated_cost": 0.05},
            {"index": 1, "description": "Main point A", "duration_s": 8.0,
             "text_overlay": "Point one", "media_method": "generate",
             "media_prompt": "person explaining concept", "estimated_cost": 0.06},
            {"index": 2, "description": "Main point B", "duration_s": 7.0,
             "text_overlay": "Point two", "media_method": "generate",
             "media_prompt": "infographic animation", "estimated_cost": 0.06},
            {"index": 3, "description": "CTA closing", "duration_s": 4.0,
             "text_overlay": "Follow for more", "media_method": "generate",
             "media_prompt": "call to action graphic", "estimated_cost": 0.04},
        ],
    }


def _make_scenes(content_type: str = "reel") -> list[Scene]:
    data = _mock_storyboard_response(content_type)
    return [Scene(**s) for s in data["scenes"]]


def _make_storyboard(content_type: str = "reel") -> Storyboard:
    scenes = _make_scenes(content_type)
    return Storyboard(
        prompt="test prompt",
        content_type=content_type,
        language="en",
        style="rafiei_reel",
        scenes=scenes,
        total_duration_s=sum(s.duration_s for s in scenes),
    )


def _make_media(storyboard: Storyboard, tmp_path: Path) -> list[dict]:
    preset = get_preset(storyboard.content_type)
    media = []
    for scene in storyboard.scenes:
        if preset["is_static"]:
            media_path = tmp_path / f"scene_{scene.index}.png"
            media_path.write_bytes(b"\x00" * 100)
        else:
            media_path = tmp_path / f"scene_{scene.index}.mp4"
            media_path.write_bytes(b"\x00" * 100)
        media.append({
            "scene_index": scene.index,
            "file_path": str(media_path),
            "source": "local_fixture",
            "cost_usd": 0.0,
            "generation_id": f"gen_{scene.index}",
            "width": preset["width"],
            "height": preset["height"],
            "duration_s": scene.duration_s,
            "fps": preset["fps"],
            "metadata": {},
        })
    return media


# ── 1. Content type presets ──────────────────────────────────────────────────

class TestContentTypePresets:
    def test_reel_preset_values(self):
        p = get_preset("reel")
        assert p["aspect"] == "9:16"
        assert p["max_duration"] == 90
        assert p["fps"] == 30
        assert p["resolution"] == "1080x1920"

    def test_post_preset_values(self):
        p = get_preset("post")
        assert p["aspect"] == "1:1"
        assert p["max_duration"] is None
        assert p["resolution"] == "1080x1080"
        assert p["is_static"] is True

    def test_story_preset_values(self):
        p = get_preset("story")
        assert p["aspect"] == "9:16"
        assert p["max_duration"] == 15
        assert p["fps"] == 30
        assert p["resolution"] == "1080x1920"

    def test_get_preset_returns_copy(self):
        a = get_preset("reel")
        b = get_preset("reel")
        a["fps"] = 999
        assert b["fps"] == 30

    def test_get_preset_unknown_raises(self):
        with pytest.raises((KeyError, ValueError)):
            get_preset("tiktok")


# ── 2. Content type enum ────────────────────────────────────────────────────

class TestContentTypeEnum:
    def test_enum_values(self):
        assert ContentType.REEL.value == "reel"
        assert ContentType.POST.value == "post"
        assert ContentType.STORY.value == "story"

    def test_enum_members(self):
        members = [m.value for m in ContentType]
        assert "reel" in members
        assert "post" in members
        assert "story" in members


# ── 3. Storyboard generation — reel ─────────────────────────────────────────

class TestStoryboardGenerationReel:
    def test_reel_has_multiple_scenes(self):
        from brain.llm import LLMUsage
        provider = _storyboard_provider((_mock_storyboard_response("reel"), LLMUsage()))
        with patch("brain.storyboard.get_provider", return_value=provider):
            sb = generate_storyboard("Make a cooking tutorial reel", "reel", "en", "rafiei_reel")
        assert isinstance(sb, Storyboard)
        assert len(sb.scenes) >= 2

    def test_reel_total_duration_within_limit(self):
        from brain.llm import LLMUsage
        provider = _storyboard_provider((_mock_storyboard_response("reel"), LLMUsage()))
        with patch("brain.storyboard.get_provider", return_value=provider):
            sb = generate_storyboard("Tutorial reel", "reel", "en", "rafiei_reel")
        total = sum(s.duration_s for s in sb.scenes)
        assert total <= 90

    def test_creative_brief_reaches_storyboard_prompt(self):
        from brain.llm import LLMUsage
        provider = _storyboard_provider((_mock_storyboard_response("reel"), LLMUsage()))
        brief = {"audience": "Persian students", "brand": "Warm terracotta"}
        with patch("brain.storyboard.get_provider", return_value=provider):
            sb = generate_storyboard("A useful habit reel", "reel", "fa", "rafiei_reel", brief)
        user_prompt = provider.generate_storyboard.call_args.args[1]["user_prompt"]
        assert "Target audience: Persian students" in user_prompt
        assert "Brand and visual identity: Warm terracotta" in user_prompt
        assert sb.creative_brief == brief
        assert Storyboard.from_dict(sb.to_dict()).creative_brief == brief

    def test_missing_provider_returns_three_scene_editable_template(self):
        with patch("brain.storyboard.get_provider", return_value=LocalFallbackProvider("text_provider_not_configured")):
            sb = generate_storyboard("Explain a useful habit", "reel", "en", "rafiei_reel")
        assert sb.is_fallback is True
        assert sb.fallback_reason == "text_provider_not_configured"
        assert [scene.description for scene in sb.scenes] == ["Intro", "Main point", "Outro"]
        assert sb.total_duration_s == 15.0
        assert sb.estimated_total_cost == 0.0
        assert Storyboard.from_dict(sb.to_dict()).is_fallback is True

    def test_provider_timeout_returns_template(self):
        provider = JarvisProvider()
        with patch.object(provider, "_chat_json", side_effect=TimeoutError("provider took too long")), \
             patch("brain.storyboard.get_provider", return_value=provider):
            sb = generate_storyboard("Explain a useful habit", "reel", "en", "rafiei_reel")

        assert sb.is_fallback is True
        assert "provider took too long" in sb.fallback_reason
        assert len(sb.scenes) == 3

    def test_non_timeout_provider_error_remains_visible(self):
        provider = JarvisProvider()
        with patch.object(provider, "_chat_json", side_effect=RuntimeError("provider rejected request")), \
             patch("brain.storyboard.get_provider", return_value=provider), \
             pytest.raises(RuntimeError, match="provider rejected request"):
            generate_storyboard("Explain a useful habit", "reel", "en", "rafiei_reel")

    def test_content_submission_persists_editable_fallback(self, tmp_path):
        job = SimpleNamespace(id="template-job", dir=tmp_path)
        with patch("app.jobs.create_job", return_value=job), \
             patch("app.jobs._write_status"), \
             patch("brain.storyboard.get_provider", return_value=LocalFallbackProvider()), \
             patch("brain.content_creator.get_provider", return_value=LocalFixtureProvider()):
            result = create_content(
                "Explain a useful habit", "reel", "en", provider_name="local_fixture",
            )

        assert result["job_id"] == "template-job"
        assert result["storyboard"]["is_fallback"] is True
        assert len(result["storyboard"]["scenes"]) == 3

        edited_scenes = result["storyboard"]["scenes"]
        edited_scenes[1]["text_overlay"] = "My edited main point"
        edited = update_storyboard(job, edited_scenes)
        assert edited is not None
        assert edited["scenes"][1]["text_overlay"] == "My edited main point"
        assert json.loads((tmp_path / "storyboard.json").read_text())["scenes"][1]["text_overlay"] == "My edited main point"

    def test_content_submission_uses_content_llm_provider_override(self, tmp_path, monkeypatch):
        job = SimpleNamespace(id="sarovi-storyboard-job", dir=tmp_path)
        storyboard = Storyboard(
            prompt="یک عادت مفید",
            content_type="reel",
            language="fa",
            style="rafiei_reel",
            scenes=[Scene(index=0, description="شروع", duration_s=5)],
        )
        monkeypatch.setenv("CONTENT_LLM_PROVIDER", "sarovi")
        with patch("app.jobs.create_job", return_value=job), \
             patch("app.jobs._write_status"), \
             patch("brain.content_creator.generate_storyboard", return_value=storyboard) as generate:
            create_content("یک عادت مفید", "reel", "fa", provider_name="local_fixture")

        assert generate.call_args.kwargs["provider_name"] == "sarovi"


# ── 4. Storyboard generation — post ─────────────────────────────────────────

class TestStoryboardGenerationPost:
    def test_post_single_scene(self):
        from brain.llm import LLMUsage
        provider = _storyboard_provider((_mock_storyboard_response("post"), LLMUsage()))
        with patch("brain.storyboard.get_provider", return_value=provider):
            sb = generate_storyboard("Product photo", "post", "en", "rafiei_reel")
        assert len(sb.scenes) == 1


# ── 5. Storyboard generation — story ────────────────────────────────────────

class TestStoryboardGenerationStory:
    def test_story_scene_count(self):
        from brain.llm import LLMUsage
        provider = _storyboard_provider((_mock_storyboard_response("story"), LLMUsage()))
        with patch("brain.storyboard.get_provider", return_value=provider):
            sb = generate_storyboard("Quick tip", "story", "en", "rafiei_reel")
        assert 1 <= len(sb.scenes) <= 3

    def test_story_total_duration_within_limit(self):
        from brain.llm import LLMUsage
        provider = _storyboard_provider((_mock_storyboard_response("story"), LLMUsage()))
        with patch("brain.storyboard.get_provider", return_value=provider):
            sb = generate_storyboard("Quick tip", "story", "en", "rafiei_reel")
        total = sum(s.duration_s for s in sb.scenes)
        assert total <= 15


# ── 6. LocalFixtureProvider — image ─────────────────────────────────────────

class TestLocalFixtureProviderImage:
    def test_generate_image_creates_file(self, tmp_path):
        provider = LocalFixtureProvider()
        result = provider.generate_image("a sunset", "9:16", tmp_path)
        assert isinstance(result, MediaResult)
        assert Path(result.file_path).exists()
        assert Path(result.file_path).stat().st_size > 0

    def test_generate_image_correct_metadata(self, tmp_path):
        provider = LocalFixtureProvider()
        result = provider.generate_image("a sunset", "1:1", tmp_path)
        assert result.source == "local_fixture"
        assert result.cost_usd == 0.0
        assert result.width > 0
        assert result.height > 0


# ── 7. LocalFixtureProvider — video ─────────────────────────────────────────

class TestLocalFixtureProviderVideo:
    def test_generate_video_creates_file(self, tmp_path):
        provider = LocalFixtureProvider()
        result = provider.generate_video("a sunset timelapse", 3.0, "9:16", tmp_path)
        assert isinstance(result, MediaResult)
        assert Path(result.file_path).exists()
        assert Path(result.file_path).stat().st_size > 0

    def test_generate_video_has_duration(self, tmp_path):
        provider = LocalFixtureProvider()
        result = provider.generate_video("sunset", 3.0, "9:16", tmp_path)
        assert result.duration_s > 0

    def test_generate_video_has_fps(self, tmp_path):
        provider = LocalFixtureProvider()
        result = provider.generate_video("sunset", 3.0, "9:16", tmp_path)
        assert result.fps > 0


def test_narration_lengthens_scene_instead_of_cutting_speech(tmp_path):
    source = tmp_path / "short.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
        "color=c=orange:s=160x284:r=30:d=1", "-c:v", "libx264", str(source),
    ], check=True)
    media = [{"scene_index": 0, "file_path": str(source), "duration_s": 1.0,
              "metadata": {}}]
    warnings = []
    _fit_video_to_narration(media, [{"scene_index": 0, "duration_s": 1.4}],
                            tmp_path, get_preset("reel"), warnings)
    actual = float(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "csv=p=0", media[0]["file_path"],
    ]))
    assert actual >= 1.55
    assert media[0]["duration_s"] == 1.6
    assert "extended" in warnings[0]


def test_narration_over_story_limit_fails_before_media_edit(tmp_path):
    media = [{"scene_index": 0, "file_path": str(tmp_path / "missing.mp4"),
              "duration_s": 14.0, "metadata": {}}]
    with pytest.raises(ValueError, match="above the 15s limit"):
        _fit_video_to_narration(media, [{"scene_index": 0, "duration_s": 16.0}],
                                tmp_path, get_preset("story"), [])


def test_story_narration_fits_without_truncating_approved_audio(tmp_path):
    voice = tmp_path / "approved_story_voice.wav"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
        "sine=frequency=440:duration=16", str(voice),
    ], check=True)
    clip = tmp_path / "jarvis_scene.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
        "color=c=blue:s=160x284:r=30:d=14", "-c:v", "libx264", str(clip),
    ], check=True)
    media = [{"scene_index": 0, "file_path": str(clip), "source": "jarvis_image_motion",
              "duration_s": 14.0, "metadata": {}}]
    narration = [{"scene_index": 0, "file_path": str(voice),
                  "duration_s": 16.0, "provider": "edge"}]
    warnings = []
    _fit_limited_narration(media, narration, tmp_path, get_preset("story"), ContentType.STORY, warnings)
    _fit_video_to_narration(media, narration, tmp_path, get_preset("story"), warnings)
    assert voice.is_file()
    assert narration[0]["timing_adjustment"] == "sped_up_for_story"
    assert 13.5 < narration[0]["duration_s"] < 14.8
    assert media[0]["duration_s"] <= 15
    assert "speed adjusted" in warnings[0]


def test_story_narration_rejects_more_than_one_point_five_speed(tmp_path):
    media = [{"scene_index": 0, "duration_s": 14.0}]
    narration = [{"scene_index": 0, "file_path": str(tmp_path / "not_needed.wav"),
                  "duration_s": 30.0}]
    with pytest.raises(ValueError, match="1.5x speech speed"):
        _fit_limited_narration(media, narration, tmp_path, get_preset("story"), ContentType.STORY, [])
    assert not list(tmp_path.iterdir())


def test_story_narration_fits_multiple_scenes_with_one_total_limit(tmp_path):
    narration = []
    media = []
    for index in range(2):
        voice = tmp_path / f"voice_{index}.wav"
        subprocess.run([
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
            "sine=frequency=440:duration=9", str(voice),
        ], check=True)
        narration.append({"scene_index": index, "file_path": str(voice), "duration_s": 9.0})
        media.append({"scene_index": index, "duration_s": 6.0})
    _fit_limited_narration(media, narration, tmp_path, get_preset("story"), ContentType.STORY, [])
    assert sum(max(m["duration_s"], round(n["duration_s"] + 0.2, 2))
               for m, n in zip(media, narration)) <= 15.0
    assert all(n["timing_adjustment"] == "sped_up_for_story" for n in narration)


def test_reel_narration_fits_ninety_second_limit(tmp_path):
    media = []
    narration = []
    for index in range(2):
        source = tmp_path / f"reel_voice_{index}.wav"
        subprocess.run([
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
            "sine=frequency=440:duration=50", str(source),
        ], check=True)
        media.append({"scene_index": index, "duration_s": 45.0})
        narration.append({"scene_index": index, "file_path": str(source),
                          "duration_s": 50.0, "provider": "edge"})
    warnings = []
    _fit_limited_narration(
        media, narration, tmp_path, get_preset("reel"), ContentType.REEL, warnings,
    )
    assert sum(max(m["duration_s"], round(n["duration_s"] + 0.2, 2))
               for m, n in zip(media, narration)) <= 90.0
    assert all(n["timing_adjustment"] == "sped_up_for_reel" for n in narration)
    assert all((tmp_path / f"reel_voice_{index}.wav").is_file() for index in range(2))
    assert "Reel voiceover speed adjusted" in warnings[0]


def test_reel_narration_within_limit_is_not_changed(tmp_path):
    source = tmp_path / "approved_voice.wav"
    record = {"scene_index": 0, "file_path": str(source), "duration_s": 12.0}
    original = record.copy()
    narration = [record]
    _fit_limited_narration(
        [{"scene_index": 0, "duration_s": 10.0}], narration,
        tmp_path, get_preset("reel"), ContentType.REEL, [],
    )
    assert narration[0] == original
    assert not list(tmp_path.iterdir())


def test_reel_narration_rejects_more_than_one_point_five_speed(tmp_path):
    with pytest.raises(ValueError, match="Reel voiceover cannot fit within 90s"):
        _fit_limited_narration(
            [{"scene_index": 0, "duration_s": 90.0}],
            [{"scene_index": 0, "file_path": str(tmp_path / "unused.wav"),
              "duration_s": 150.0}],
            tmp_path, get_preset("reel"), ContentType.REEL, [],
        )


def test_jarvis_story_generation_fits_voice_and_writes_plan(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTENT_VOICE_PROVIDER", "edge")
    monkeypatch.setenv("SAROVI_API_KEY", "")
    generated = tmp_path / "generated"
    generated.mkdir()
    clip = generated / "jarvis_scene.mp4"
    voice = generated / "approved_voice.wav"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
        "color=c=green:s=160x284:r=30:d=14", "-c:v", "libx264", str(clip),
    ], check=True)
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
        "sine=frequency=440:duration=16", str(voice),
    ], check=True)
    storyboard = Storyboard(
        prompt="A story", content_type="story", language="en", style="rafiei_reel",
        scenes=[Scene(index=0, description="Scene", duration_s=14,
                      narration_text="Approved words stay intact", media_prompt="A scene")],
    )
    (tmp_path / "storyboard.json").write_text(json.dumps(storyboard.to_dict()))
    (tmp_path / "generation_status.json").write_text(json.dumps({"state": "generating"}))
    job = SimpleNamespace(id="jarvis-story", dir=tmp_path, raw_name=None)
    provider = MagicMock()
    provider.generate_video.return_value = MediaResult(
        file_path=str(clip), source="jarvis_image_motion", duration_s=14.0,
        width=160, height=284, fps=30,
    )
    with patch("app.jobs.get", return_value=job), \
         patch("app.jobs._write_status"), \
         patch("brain.content_creator.get_provider", return_value=provider), \
         patch("brain.tts.generate_narration", return_value=SimpleNamespace(
             file_path=str(voice), duration_s=16.0,
         )), \
         patch("brain.asset_match.music_match", return_value=[]):
        _run_generation(job.id, "jarvis_image", raise_errors=True)

    assert json.loads((tmp_path / "generation_status.json").read_text())["state"] == "ready"
    plan = job.plan_data
    assert plan["generation_meta"]["provider"] == "jarvis_image_motion"
    assert Path(plan["sfx"][0]["file"]).is_file()
    assert voice.is_file()
    assert float(plan["segments"][0]["out"]) <= 15


def test_post_narration_is_sped_up_without_cutting_approved_audio(tmp_path):
    source = tmp_path / "approved_voice.wav"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
        "sine=frequency=440:duration=6.48", str(source),
    ], check=True)
    warnings = []
    fitted = _fit_post_narration(
        {"scene_index": 0, "file_path": str(source), "duration_s": 6.48,
         "provider": "sarovi"}, tmp_path, warnings,
    )
    assert 4.4 < fitted["duration_s"] <= 4.8
    assert fitted["original_duration_s"] == 6.48
    assert fitted["timing_adjustment"] == "sped_up_for_post"
    assert source.is_file()
    assert "speed adjusted" in warnings[0]
    media = [{"scene_index": 0, "duration_s": 5.0}]
    _fit_video_to_narration(media, [fitted], tmp_path, get_preset("post"), warnings)


def test_post_narration_rejects_unintelligible_speed(tmp_path):
    with pytest.raises(ValueError, match="more than 1.5x"):
        _fit_post_narration(
            {"scene_index": 0, "file_path": str(tmp_path / "not_needed.wav"),
             "duration_s": 9.0}, tmp_path, [],
        )


# ── 8. storyboard_to_plan — reel ────────────────────────────────────────────

class TestStoryboardToPlanReel:
    def test_produces_valid_plan(self, tmp_path):
        sb = _make_storyboard("reel")
        media = _make_media(sb, tmp_path)
        source = str(tmp_path / "stitched.mp4")
        Path(source).write_bytes(b"\x00" * 100)
        plan_data = storyboard_to_plan(sb, media, ContentType.REEL, source)
        assert "segments" in plan_data
        assert plan_data["captions"][0]["style"] == "cover"
        assert plan_data["captions"][-1]["style"] == "cta"
        assert "canvas" in plan_data
        assert len(plan_data["segments"]) == len(sb.scenes)
        plan, errors = validate_plan(plan_data, check_media=False)
        assert errors == [], f"Validation errors: {errors}"

    def test_canvas_dimensions_match_reel(self, tmp_path):
        sb = _make_storyboard("reel")
        media = _make_media(sb, tmp_path)
        source = str(tmp_path / "stitched.mp4")
        Path(source).write_bytes(b"\x00" * 100)
        plan_data = storyboard_to_plan(sb, media, ContentType.REEL, source)
        assert plan_data["canvas"]["width"] == 1080
        assert plan_data["canvas"]["height"] == 1920


# ── 9. storyboard_to_plan — post ────────────────────────────────────────────

class TestStoryboardToPlanPost:
    def test_post_single_segment(self, tmp_path):
        sb = _make_storyboard("post")
        media = _make_media(sb, tmp_path)
        source = str(media[0]["file_path"])
        plan_data = storyboard_to_plan(sb, media, ContentType.POST, source)
        assert len(plan_data["segments"]) == 1
        assert plan_data["canvas"]["width"] == 1080
        assert plan_data["canvas"]["height"] == 1080
        plan, errors = validate_plan(plan_data, check_media=False)
        assert errors == [], f"Validation errors: {errors}"


# ── 10. storyboard_to_plan — story ──────────────────────────────────────────

class TestStoryboardToPlanStory:
    def test_story_validates(self, tmp_path):
        sb = _make_storyboard("story")
        media = _make_media(sb, tmp_path)
        source = str(tmp_path / "stitched.mp4")
        Path(source).write_bytes(b"\x00" * 100)
        plan_data = storyboard_to_plan(sb, media, ContentType.STORY, source)
        plan, errors = validate_plan(plan_data, check_media=False)
        assert errors == [], f"Validation errors: {errors}"


# ── 11. Full flow (unit, no job system) ───────────────────────────────────────

class TestFullFlow:
    def test_storyboard_to_plan_round_trip(self, tmp_path):
        from brain.llm import LLMUsage
        provider = _storyboard_provider((_mock_storyboard_response("reel"), LLMUsage()))
        with patch("brain.storyboard.get_provider", return_value=provider):
            sb = generate_storyboard("Make a motivational reel", "reel", "en", "rafiei_reel")
        assert len(sb.scenes) > 0

        media = _make_media(sb, tmp_path)
        source = str(tmp_path / "stitched.mp4")
        Path(source).write_bytes(b"\x00" * 100)

        plan_data = storyboard_to_plan(sb, media, ContentType.REEL, source)
        plan, errors = validate_plan(plan_data, check_media=False)
        assert errors == [], f"Validation errors: {errors}"
        assert plan_data.get("content_type") == "reel"
        assert plan_data.get("source_type") == "generated"


# ── 12. POST exports image ──────────────────────────────────────────────────

class TestPostExportsImage:
    def test_post_generates_image_media(self, tmp_path):
        provider = LocalFixtureProvider()
        result = provider.generate_image("Product shot", "1:1", tmp_path)
        assert Path(result.file_path).exists()
        assert result.file_path.endswith(".png")


# ── 13. Backward compatibility ──────────────────────────────────────────────

class TestBackwardCompat:
    def test_existing_plan_without_content_fields(self):
        plan_data = {
            "version": "0.1",
            "style": "rafiei_reel",
            "canvas": {"width": 1080, "height": 1920, "fps": 30},
            "source": "raw/test.mp4",
            "segments": [{"id": "s1", "in": 0.0, "out": 5.0}],
            "export": {"file": "exports/v1.mp4"},
        }
        plan, errors = validate_plan(plan_data, check_media=False)
        assert errors == [], f"Backward compat broken: {errors}"
        assert plan is not None

    def test_plan_with_content_fields_also_validates(self):
        plan_data = {
            "version": "0.1",
            "style": "rafiei_reel",
            "canvas": {"width": 1080, "height": 1920, "fps": 30},
            "source": "raw/test.mp4",
            "segments": [{"id": "s1", "in": 0.0, "out": 5.0}],
            "export": {"file": "exports/v1.mp4"},
            "content_type": "reel",
            "source_type": "generated",
            "generation_meta": {"provider": "local_fixture", "total_cost": 0.0},
        }
        plan, errors = validate_plan(plan_data, check_media=False)
        assert errors == [], f"Validation errors: {errors}"


# ── 14. Provider registry ───────────────────────────────────────────────────

class TestProviderRegistry:
    def test_register_and_get(self):
        mock_provider = MagicMock()
        register_provider("test_provider_xyz", mock_provider)
        retrieved = get_provider("test_provider_xyz")
        assert retrieved is mock_provider
        del _registry["test_provider_xyz"]

    def test_get_unknown_provider_raises(self):
        with pytest.raises((KeyError, ValueError)):
            get_provider("nonexistent_provider_xyz")

    def test_local_fixture_always_available(self):
        provider = get_provider("local_fixture")
        assert isinstance(provider, LocalFixtureProvider)

    def test_list_providers_includes_local(self):
        providers = list_providers()
        names = [p["name"] for p in providers]
        assert "local_fixture" in names

    def test_list_providers_exposes_key_status_expected_by_ui(self):
        provider = next(p for p in list_providers() if p["name"] == "jarvis_image")
        assert provider["key_configured"] is provider["has_key"]


class TestJarvisImageProvider:
    @staticmethod
    def _png_base64() -> str:
        from PIL import Image
        buffer = io.BytesIO()
        Image.new("RGB", (8, 8), (40, 120, 200)).save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("ascii")

    def test_image_generation_uses_configured_jarvis_endpoint(self, tmp_path):
        provider = JarvisImageProvider()
        response = SimpleNamespace(data=[SimpleNamespace(b64_json=self._png_base64())])
        client = MagicMock()
        client.images.generate.return_value = response
        with patch.dict("os.environ", {
            "JARVIS_API_KEY": "unit-test-key",
            "IMAGE_BASE_URL": "https://api.jarvis.you/v1/images",
            "IMAGE_MODEL": "configured-image-model",
        }, clear=True), patch("openai.OpenAI", return_value=client) as openai_client:
            result = provider.generate_image("A product photo", "1:1", tmp_path)

        openai_client.assert_called_once_with(
            api_key="unit-test-key", base_url="https://api.jarvis.you/v1",
            timeout=180, max_retries=0,
        )
        client.images.generate.assert_called_once()
        call = client.images.generate.call_args.kwargs
        assert call["model"] == "configured-image-model"
        assert call["size"] == "1024x1024"
        assert Path(result.file_path).is_file()
        assert result.source == "jarvis_image"
        assert result.cost_usd is None

    def test_image_provider_uses_configured_fallback_after_upstream_5xx(self, tmp_path):
        provider = JarvisImageProvider()
        response = SimpleNamespace(data=[SimpleNamespace(b64_json=self._png_base64())])
        client = MagicMock()

        class Gateway503Error(Exception):
            status_code = 503

        client.images.generate.side_effect = [Gateway503Error("service unavailable"), response]
        with patch.dict("os.environ", {
            "JARVIS_API_KEY": "unit-test-key",
            "IMAGE_BASE_URL": "https://api.jarvis.you/v1/images",
            "IMAGE_MODEL": "primary-image-model",
            "IMAGE_FALLBACK_MODEL": "fallback-image-model",
        }, clear=True), patch("openai.OpenAI", return_value=client):
            result = provider.generate_image("A product photo", "1:1", tmp_path)
        assert result.metadata["model"] == "fallback-image-model"
        assert result.metadata["fallback_used"] is True
        assert [call.kwargs["model"] for call in client.images.generate.call_args_list] == [
            "primary-image-model", "fallback-image-model",
        ]


class TestContentProviderSelection:
    def test_approval_uses_provider_selected_during_storyboard_creation(self, tmp_path):
        from brain.content_creator import approve_and_generate
        status_path = tmp_path / "generation_status.json"
        status_path.write_text(json.dumps({"state": "pending", "provider": "jarvis_image"}))
        job = SimpleNamespace(id="content-job", dir=tmp_path)
        thread = MagicMock()
        with patch("brain.content_creator.get_provider", return_value=SimpleNamespace(has_key=True)), \
             patch("brain.content_creator.CELERY_AVAILABLE", False), \
             patch("brain.content_creator.threading.Thread", return_value=thread) as thread_class:
            approve_and_generate(job)
        thread_class.assert_called_once()
        assert thread_class.call_args.kwargs["args"] == ("content-job", "jarvis_image")
        thread.start.assert_called_once()
        assert json.loads(status_path.read_text())["provider"] == "jarvis_image"

    def test_plan_does_not_claim_unknown_provider_cost_is_zero(self, tmp_path):
        storyboard = _make_storyboard("post")
        media = [{
            "scene_index": 0, "file_path": str(tmp_path / "product.png"),
            "source": "jarvis_image", "cost_usd": None,
        }]
        Path(media[0]["file_path"]).write_bytes(b"image placeholder")
        plan = storyboard_to_plan(
            storyboard, media, ContentType.POST, media[0]["file_path"],
        )
        assert plan["generation_meta"]["total_cost"] is None
        assert plan["generation_meta"]["cost_status"] == "not_reported_by_provider"

    def test_image_provider_rejects_missing_key_without_network_call(self, tmp_path):
        provider = JarvisImageProvider()
        with patch.dict("os.environ", {"IMAGE_MODEL": "configured-image-model"}, clear=True):
            with pytest.raises(RuntimeError, match="Set IMAGE_API_KEY"):
                provider.generate_image("A product photo", "1:1", tmp_path)

    def test_image_to_video_produces_playable_clip(self, tmp_path, monkeypatch):
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            pytest.skip("ffmpeg and ffprobe are required")
        from PIL import Image
        still_path = tmp_path / "source.png"
        Image.new("RGB", (96, 96), (20, 80, 140)).save(still_path)
        provider = JarvisImageProvider()
        monkeypatch.setattr("brain.media_provider._parse_resolution", lambda _aspect: (64, 128))
        monkeypatch.setattr(provider, "generate_image", lambda *_args: MediaResult(
            file_path=str(still_path), source="jarvis_image", cost_usd=None,
            generation_id="image-test", width=96, height=96,
        ))

        result = provider.generate_video("A vertical scene", 1.0, "9:16", tmp_path)
        metadata = json.loads(subprocess.check_output([
            "ffprobe", "-v", "error", "-show_entries", "stream=width,height,codec_name",
            "-show_entries", "format=duration", "-of", "json", result.file_path,
        ], text=True))
        video = next(stream for stream in metadata["streams"] if stream["codec_name"] == "h264")
        assert (video["width"], video["height"]) == (64, 128)
        assert 0.95 <= float(metadata["format"]["duration"]) <= 1.1
        assert result.cost_usd is None


# ── 15. Storyboard edit ─────────────────────────────────────────────────────

class TestStoryboardEdit:
    def test_reorder_scenes(self):
        sb = _make_storyboard("reel")
        original_first_desc = sb.scenes[0].description
        reordered = list(reversed(sb.scenes))
        for i, scene in enumerate(reordered):
            scene.index = i
        sb.scenes = reordered
        assert sb.scenes[0].description != original_first_desc
        assert sb.scenes[-1].description == original_first_desc

    def test_delete_scene(self):
        sb = _make_storyboard("reel")
        original_count = len(sb.scenes)
        sb.scenes = [s for s in sb.scenes if s.index != 1]
        for i, scene in enumerate(sb.scenes):
            scene.index = i
        assert len(sb.scenes) == original_count - 1

    def test_edit_text_overlay(self):
        sb = _make_storyboard("reel")
        sb.scenes[0].text_overlay = "Changed text"
        assert sb.scenes[0].text_overlay == "Changed text"

    def test_from_dict_round_trip(self):
        sb = _make_storyboard("story")
        d = sb.to_dict()
        restored = Storyboard.from_dict(d)
        assert restored.content_type == "story"
        assert restored.language == sb.language
        assert restored.style == sb.style
        assert len(restored.scenes) == len(sb.scenes)
        assert restored.scenes[0].description == sb.scenes[0].description


class TestNarration:
    def test_storyboard_narration_round_trip_and_persian_prompt(self):
        scene = Scene(index=0, description="A scene", duration_s=5,
                      narration_text="سلام به شما")
        storyboard = Storyboard(prompt="test", content_type="post", language="fa",
                                style="rafiei_reel", scenes=[scene])
        restored = Storyboard.from_dict(storyboard.to_dict())
        assert restored.scenes[0].narration_text == "سلام به شما"
        assert restored.scenes[0].narration_voice == "default"
        prompt = _build_storyboard_system_prompt(get_preset("post"), ContentType.POST, "fa")
        assert "narration_text MUST be in Persian script" in prompt

    def test_plan_keeps_voiceover_and_quiet_background_as_separate_tracks(self, tmp_path):
        storyboard = _make_storyboard("post")
        media = _make_media(storyboard, tmp_path)
        narration = str(tmp_path / "narration.mp3")
        background = str(tmp_path / "background.mp3")
        plan_data = storyboard_to_plan(
            storyboard, media, ContentType.POST, media[0]["file_path"],
            narration_path=narration, background_music_path=background,
        )
        assert plan_data["music"] == {"file": background, "volume_db": -24.0, "duck": []}
        assert plan_data["sfx"] == [{"at": 0.0, "file": narration, "volume_db": 0.0}]
        _, errors = validate_plan(plan_data, check_media=False)
        assert errors == []

    def test_tts_without_key_uses_persian_voice(self, tmp_path):
        from brain.tts import generate_narration
        async def fake_generate(text, output_path, voice, rate):
            assert text == "سلام"
            assert voice == "fa-IR-DilaraNeural"
            assert rate == "+0%"
            Path(output_path).write_bytes(b"mock-mp3")

        with patch.dict("os.environ", {
            "ELEVENLABS_API_KEY": "", "TTS_VOICE_ID": "fa-IR-DilaraNeural",
            "TTS_RATE": "+0%",
        }), patch("brain.tts._generate_async", side_effect=fake_generate), \
             patch("brain.tts._get_audio_duration", return_value=1.25):
            result = generate_narration("سلام", tmp_path)
        assert Path(result.file_path).read_bytes() == b"mock-mp3"
        assert result.duration_s == 1.25
        assert result.cost_usd == 0.0

    def test_narration_assembly_preserves_silent_scene(self, tmp_path):
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            pytest.skip("ffmpeg and ffprobe are required")
        tone = tmp_path / "tone.mp3"
        subprocess.run([
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi",
            "-i", "sine=frequency=440:duration=0.3", str(tone),
        ], check=True, capture_output=True)
        output = _concat_audio(
            [{"scene_index": 1, "file_path": str(tone), "duration_s": 0.3}],
            tmp_path,
            [{"scene_index": 0, "duration_s": 0.3},
             {"scene_index": 1, "duration_s": 0.3}],
        )
        duration = float(subprocess.check_output([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", output,
        ], text=True).strip())
        assert 0.58 <= duration <= 0.64
        pcm = subprocess.check_output([
            "ffmpeg", "-v", "error", "-i", output, "-f", "s16le",
            "-ac", "1", "-ar", "44100", "pipe:1",
        ])
        from array import array
        samples = array("h", pcm)
        assert max(abs(v) for v in samples[:int(0.2 * 44100)]) == 0
        assert max(abs(v) for v in samples[int(0.4 * 44100):]) > 0

    def test_generation_saves_narration_and_background_in_plan(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SAROVI_API_KEY", "")
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            pytest.skip("ffmpeg and ffprobe are required")
        generated = tmp_path / "generated"
        generated.mkdir()
        video = generated / "scene.mp4"
        video.write_bytes(b"video placeholder")
        tone = tmp_path / "tone.mp3"
        subprocess.run([
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi",
            "-i", "sine=frequency=440:duration=0.3", str(tone),
        ], check=True, capture_output=True)
        storyboard = Storyboard(
            prompt="test", content_type="reel", language="en", style="rafiei_reel",
            scenes=[Scene(index=0, description="Test", duration_s=0.5,
                          narration_text="Hello", media_prompt="a scene")],
        )
        (tmp_path / "storyboard.json").write_text(json.dumps(storyboard.to_dict()))
        (tmp_path / "generation_status.json").write_text(json.dumps({"state": "generating"}))
        job = SimpleNamespace(id="narration-job", dir=tmp_path, raw_name=None)
        provider = MagicMock()
        provider.generate_video.return_value = MediaResult(
            file_path=str(video), source="local_fixture", duration_s=0.5,
        )
        with patch("app.jobs.get", return_value=job), \
             patch("app.jobs._write_status"), \
             patch("brain.content_creator.get_provider", return_value=provider), \
             patch("brain.tts.generate_narration", return_value=SimpleNamespace(
                 file_path=str(tone), duration_s=0.3,
             )), \
             patch("brain.asset_match.music_match", return_value=[SimpleNamespace(path=str(tone))]):
            _run_generation(job.id, "local_fixture", raise_errors=True)

        plan = job.plan_data
        assert Path(plan["music"]["file"]).is_file()
        assert plan["music"]["file"] == str(tone)
        assert plan["sfx"][0]["file"].endswith("narration_full.mp3")
        assert plan["sfx"][0]["volume_db"] == 0.0
        assert json.loads((tmp_path / "generation_status.json").read_text())["state"] == "ready"
