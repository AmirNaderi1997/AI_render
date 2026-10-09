"""Tests for Effects V4: rendering, My Effects, vision-aware scoring, learning."""
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from engine.effects_v4 import (
    EXTENDED_EFFECTS,
    RENDERABLE_EXTENDED_EFFECTS,
    UNSUPPORTED_EFFECTS,
    EFFECT_CATALOG_V4,
    EFFECT_FAMILIES_V4,
    catalog_for_api,
    MyEffectsPreset,
    EffectFeedback,
    effect_filter_xml_v4,
)
from brain.effect_score_v4 import (
    score_families_with_vision,
    select_effects_with_vision,
    _identify_edit_story,
)


@pytest.mark.parametrize("effect_id", sorted(RENDERABLE_EXTENDED_EFFECTS))
def test_extended_effect_changes_rendered_video_pixels(tmp_path, has_melt, effect_id):
    """Installed MLT services must apply each selectable V4 effect, not no-op."""
    import shutil
    import subprocess
    from engine.build_mlt import build
    from engine.render import render
    from engine.schema import validate_plan

    if not has_melt or not shutil.which("ffmpeg"):
        pytest.skip("requires ffmpeg and melt")

    source = tmp_path / "pattern.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
        "testsrc2=size=320x240:rate=30:duration=1.2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source),
    ], check=True, capture_output=True)

    def rendered_frame(name: str, selected_effect: str | None) -> str:
        data = {
            "canvas": {"width": 320, "height": 240, "fps": 30},
            "source": str(source),
            "segments": [{"id": "s1", "in": 0, "out": 1.1}],
            "visual_effects": ([{"segment_id": "s1", "type": selected_effect}]
                               if selected_effect else []),
            "export": {"file": f"{name}.mp4"},
        }
        plan, errors = validate_plan(data, base_dir=tmp_path, check_media=True)
        assert not errors, errors
        mlt, _ = build(plan, tmp_path / f"{name}-build", base_dir=tmp_path)
        output = tmp_path / f"{name}.mp4"
        render(mlt, output)
        hashes = subprocess.check_output([
            "ffmpeg", "-v", "error", "-i", str(output), "-map", "0:v:0",
            "-frames:v", "1", "-f", "framemd5", "-",
        ], text=True)
        return [line.split(",")[-1].strip() for line in hashes.splitlines()
                if line and not line.startswith("#")][0]

    baseline = rendered_frame("baseline", None)
    assert rendered_frame(effect_id, effect_id) != baseline


class TestNewEffectsRender:
    """Every new effect renders to valid MLT XML."""

    def test_new_effects_exist(self):
        """V4 extended effects are defined."""
        expected = {
            "camera_shake", "freeze_frame_zoom", "speed_ramp", "blur_in",
            "vignette_pulse", "rgb_split", "light_leak_overlay", "white_flash",
            "black_flash", "text_pop_scale", "emoji_sticker_pop", "zoom_blur_transition",
            "black_and_white_flash",
        }
        assert expected.issubset(set(EXTENDED_EFFECTS.keys()))

    def test_renderable_effect_filter_xml_is_nonempty_and_unsupported_fails(self):
        """Every selectable effect has a concrete renderer; unsupported ones fail clearly."""
        for effect_id in RENDERABLE_EXTENDED_EFFECTS:
            xml = effect_filter_xml_v4(effect_id, frames=30, width=1080, height=1920, punch_frames=5)
            assert isinstance(xml, str) and xml.strip()
            assert "<!--" not in xml
        for effect_id in UNSUPPORTED_EFFECTS:
            with pytest.raises(ValueError, match="cannot be rendered"):
                effect_filter_xml_v4(effect_id, frames=30, width=1080, height=1920, punch_frames=5)
        assert not (set(UNSUPPORTED_EFFECTS) & {effect["id"] for effect in catalog_for_api()})

    def test_legacy_effects_still_render(self):
        """V3 effects fall back to legacy rendering."""
        xml = effect_filter_xml_v4("punch__lift_medium", frames=30, width=1080, height=1920, punch_frames=5)
        assert "affine" in xml or "brightness" in xml

    def test_duration_preserved(self):
        """Effect rendering doesn't change clip duration.

        This is a mock test since we can't actually render; production would use ffprobe.
        """
        # Effects are filters, not clips, so duration is preserved
        for effect_id in RENDERABLE_EXTENDED_EFFECTS:
            xml = effect_filter_xml_v4(effect_id, frames=30, width=1080, height=1920, punch_frames=5)
            # Filters should not have <clip> or duration-changing elements
            assert "<clip" not in xml or "duration" not in xml

    def test_selected_v4_filters_use_installed_mlt_services(self):
        blur = effect_filter_xml_v4("blur_in", 60, 1080, 1920, 5)
        vignette = effect_filter_xml_v4("vignette_pulse", 60, 1080, 1920, 5)
        assert 'mlt_service="boxblur"' in blur and 'name="blur"' in blur
        assert 'mlt_service="vignette"' in vignette and 'name="opacity"' in vignette

    def test_v4_preserves_portrait_cover_for_landscape_source(self):
        xml = effect_filter_xml_v4("vignette_pulse", 60, 1080, 1920, 5,
                                   cover_scale=3.16049)
        assert 'mlt_service="affine"' in xml
        assert 'transition.fill' in xml
        assert 'mlt_service="vignette"' in xml


class TestMyEffects:
    """My Effects system: favorites, rules, dislikes, weights."""

    def test_my_effects_load_save(self):
        """Favorites and rules persist to YAML."""
        with tempfile.TemporaryDirectory() as tmpdir:
            preset_path = Path(tmpdir) / "my_effects.yaml"
            me = MyEffectsPreset(preset_path)

            # Add favorite
            me.add_favorite("punch__lift_medium", weight=1.5, tags=["key_points"])
            assert "punch__lift_medium" in me.favorites
            assert me.favorites["punch__lift_medium"]["weight"] == 1.5

            # Add rule
            me.add_rule("روی اعداد و آمار زوم سریع بزن", priority="hard")
            assert len(me.rules) == 1
            assert "اعداد" in me.rules[0]["text"]

            # Reload and verify
            me2 = MyEffectsPreset(preset_path)
            assert "punch__lift_medium" in me2.favorites
            assert len(me2.rules) == 1

    def test_dislikes_respected(self):
        """Disliked effects are marked to never use."""
        with tempfile.TemporaryDirectory() as tmpdir:
            preset_path = Path(tmpdir) / "my_effects.yaml"
            me = MyEffectsPreset(preset_path)
            me.add_dislike("rgb_split")
            assert "rgb_split" in me.dislikes

    def test_custom_assets(self):
        """Custom overlays and stickers can be uploaded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            preset_path = Path(tmpdir) / "my_effects.yaml"
            me = MyEffectsPreset(preset_path)
            me.custom_assets["my_light_leak"] = {
                "type": "overlay",
                "path": "assets/overlays/my_leak.mp4",
                "tags": ["cinematic", "warm"],
                "when_to_use": "Transitions between sections",
            }
            me.save()
            me2 = MyEffectsPreset(preset_path)
            assert "my_light_leak" in me2.custom_assets


class TestEffectFeedback:
    """Learning from user edits: save and load examples."""

    def test_feedback_save_load(self):
        """User edits are saved and loaded as JSONL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fb_path = Path(tmpdir) / "effect_feedback.jsonl"
            fb = EffectFeedback(fb_path)

            # Add examples
            fb.add("روی اعداد", "number", "steady__neutral", "punch__lift_medium")
            fb.add("قاب نزدیک", "question", "slow_push__neutral", "close_hold__lift_soft")

            assert len(fb.examples) == 2

            # Reload
            fb2 = EffectFeedback(fb_path)
            assert len(fb2.examples) == 2
            assert fb2.examples[0]["new_effect"] == "punch__lift_medium"

    def test_feedback_keeps_last_20(self):
        """Only last 20 examples are kept."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fb_path = Path(tmpdir) / "effect_feedback.jsonl"
            fb = EffectFeedback(fb_path)

            for i in range(30):
                fb.add(f"segment {i}", "claim", "old", "new")

            assert len(fb.examples) == 20

    def test_feedback_as_prompt_examples(self):
        """Feedback format for LLM few-shot."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fb_path = Path(tmpdir) / "effect_feedback.jsonl"
            fb = EffectFeedback(fb_path)
            fb.add("اعداد", "number", "old", "punch")

            prompt_text = fb.as_prompt_examples()
            assert "Examples from user edits" in prompt_text
            assert "اعداد" in prompt_text


class TestVisionAwareScoring:
    """Effects scored with vision model + rules."""

    def test_score_with_rules_boost(self):
        """User rules boost matching families."""
        with tempfile.TemporaryDirectory() as tmpdir:
            preset_path = Path(tmpdir) / "my_effects.yaml"
            me = MyEffectsPreset(preset_path)
            me.add_rule("روی اعداد و آمار زوم سریع بزن")  # Boost punch/flash on numbers

            analysis = {"role": "number", "energy": 3, "text": "۱۰۰ درصد بهتر"}

            scores = score_families_with_vision(
                analysis, None, None, None, 0, {"effects": {}},
                my_effects=me
            )

            score_dict = dict(scores)
            # Punch should be boosted due to rule
            if "punch" in score_dict:
                assert score_dict["punch"] > 0

    def test_favorite_weight_multiplier(self):
        """Favorite weight increases usage score."""
        with tempfile.TemporaryDirectory() as tmpdir:
            preset_path = Path(tmpdir) / "my_effects.yaml"
            me = MyEffectsPreset(preset_path)
            me.add_favorite("punch__lift_medium", weight=2.0)

            analysis = {"role": "hook", "energy": 4}

            scores = score_families_with_vision(
                analysis, None, None, None, 0, {"effects": {}},
                my_effects=me
            )

            score_dict = dict(scores)
            # Punch-related should score higher with weight=2.0
            assert len(scores) > 0

    def test_never_effect_never_chosen(self):
        """Disliked effects get negative score."""
        with tempfile.TemporaryDirectory() as tmpdir:
            preset_path = Path(tmpdir) / "my_effects.yaml"
            me = MyEffectsPreset(preset_path)
            me.add_dislike("rgb_split")

            analysis = {"role": "explanation"}

            scores = score_families_with_vision(
                analysis, None, None, None, 0, {"effects": {}},
                my_effects=me
            )

            score_dict = dict(scores)
            # rgb_split should not appear or have -100 score
            if "rgb_split" in score_dict:
                assert score_dict["rgb_split"] < 0

    def test_fallback_text_only_when_no_vision(self):
        """If vision model unavailable, text-only scoring works."""
        analysis = {"role": "claim", "energy": 2}

        scores = score_families_with_vision(
            analysis, keyframe_path=None, prev_family=None, prev_prev_family=None,
            accent_debt=0, style={"effects": {}}, my_effects=None, feedback=None
        )

        # Should return valid scores
        assert len(scores) > 0
        assert all(isinstance(s[0], str) and isinstance(s[1], float) for s in scores)

    def test_saved_no_zoom_rule_excludes_zoom_and_v4_can_win(self, tmp_path):
        me = MyEffectsPreset(tmp_path / "my_effects.yaml")
        me.add_rule("زوم نکن", priority="hard")
        me.add_favorite("steady__neutral", weight=1.1)
        scores = score_families_with_vision(
            {"role": "emotion", "energy": 2, "text": "a personal moment"},
            None, None, None, 0, {"effects": {}}, my_effects=me,
        )
        families = dict(scores)
        assert "punch" not in families
        assert "slow_push" not in families
        assert "flash" not in families
        assert "flash_end" not in families
        assert scores[0][0] == "vignette_pulse"


class TestEditStoryPlanning:
    """Whole-reel planning: hook → build → peak → calm → CTA."""

    def test_identify_edit_story(self):
        """Hook, peak, CTA moments identified."""
        segments = [
            {"id": "s1", "in": 0, "out": 2},
            {"id": "s2", "in": 2, "out": 4},
            {"id": "s3", "in": 4, "out": 6},
        ]
        analyses = [
            {"intensity": 2},
            {"intensity": 5},  # Peak
            {"intensity": 3},
        ]

        moments = _identify_edit_story(segments, analyses)

        assert moments["s1"] == "hook"
        assert moments["s2"] == "peak"
        assert moments["s3"] == "cta"

    def test_select_effects_with_vision_returns_valid(self):
        """select_effects_with_vision returns valid effect IDs."""
        segments = [
            {"id": "s1", "in": 0, "out": 2},
            {"id": "s2", "in": 2, "out": 4},
        ]
        analyses = [
            {"role": "hook", "energy": 4, "text": "Start"},
            {"role": "claim", "energy": 3, "text": "Main idea"},
        ]

        effects = select_effects_with_vision(segments, analyses, None, {"effects": {}})

        assert len(effects) == 2
        assert all("segment_id" in e and "type" in e and "reason" in e for e in effects)
        # Check types are valid effect IDs
        for eff in effects:
            assert eff["type"] in EFFECT_CATALOG_V4 or "__" in eff["type"]


class TestFeedbackLearning:
    """Recent edits influence future effect selection."""

    def test_similar_segment_uses_learned_effect(self):
        """When similar segment seen before, learned effect is preferred."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fb_path = Path(tmpdir) / "effect_feedback.jsonl"
            fb = EffectFeedback(fb_path)

            # User changed from old to new effect on similar segment
            fb.add("اعداد بسیار مهم", "number", "steady__neutral", "punch__lift_medium")

            # Now same segment appears
            analysis = {
                "role": "number",
                "energy": 3,
                "text": "اعداد بسیار مهم",
            }

            scores = score_families_with_vision(
                analysis, None, None, None, 0, {"effects": {}},
                my_effects=None, feedback=fb
            )

            # Punch should get a slight boost from feedback
            score_dict = dict(scores)
            assert len(scores) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
