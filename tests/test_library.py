"""Tests for Stage 3: asset library indexer and matchers."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

# Import the FastAPI app at module load — before any fixture patches
# engine.schema.PROJECT_ROOT — so that module-level path constants (e.g. the
# presets directory) bind to the real project root rather than a pytest tmp dir.
from app.main import app as _app


@pytest.fixture
def lib_root(tmp_path):
    """Create a temporary library with sample assets and sidecars."""
    import engine.library as lib
    original_root = lib.LIBRARY_ROOT
    original_index = lib.INDEX_PATH
    lib.LIBRARY_ROOT = tmp_path
    lib.INDEX_PATH = tmp_path / "library_index.json"

    # Also patch PROJECT_ROOT for relative path computation
    import engine.schema
    original_project = engine.schema.PROJECT_ROOT
    engine.schema.PROJECT_ROOT = tmp_path.parent

    for cat in ("broll", "music", "sfx"):
        (tmp_path / cat).mkdir()

    # Create dummy media files
    (tmp_path / "broll" / "city_timelapse.mp4").write_bytes(b"\x00" * 100)
    (tmp_path / "broll" / "city_timelapse.yaml").write_text(
        yaml.dump({"tags": ["city", "urban", "timelapse"], "mood": "energetic", "energy": 4,
                   "description": "City skyline at sunset"}))

    (tmp_path / "broll" / "nature_forest.mp4").write_bytes(b"\x00" * 100)
    (tmp_path / "broll" / "nature_forest.yaml").write_text(
        yaml.dump({"tags": ["nature", "forest", "green"], "mood": "calm", "energy": 1}))

    (tmp_path / "broll" / "office_desk.mp4").write_bytes(b"\x00" * 100)
    (tmp_path / "broll" / "office_desk.yaml").write_text(
        yaml.dump({"tags": ["office", "desk", "work"], "mood": "neutral", "energy": 2}))

    (tmp_path / "music" / "upbeat_track.mp3").write_bytes(b"\x00" * 100)
    (tmp_path / "music" / "upbeat_track.yaml").write_text(
        yaml.dump({"tags": ["upbeat", "happy", "pop"], "mood": "happy", "energy": 4}))

    (tmp_path / "music" / "calm_piano.mp3").write_bytes(b"\x00" * 100)
    (tmp_path / "music" / "calm_piano.yaml").write_text(
        yaml.dump({"tags": ["calm", "piano", "ambient"], "mood": "calm", "energy": 1}))

    (tmp_path / "sfx" / "whoosh_01.wav").write_bytes(b"\x00" * 100)
    (tmp_path / "sfx" / "whoosh_01.yaml").write_text(
        yaml.dump({"tags": ["whoosh", "transition", "swoosh"]}))

    (tmp_path / "sfx" / "pop_click.wav").write_bytes(b"\x00" * 100)
    (tmp_path / "sfx" / "pop_click.yaml").write_text(
        yaml.dump({"tags": ["pop", "click", "notification"]}))

    yield tmp_path

    lib.LIBRARY_ROOT = original_root
    lib.INDEX_PATH = original_index
    engine.schema.PROJECT_ROOT = original_project


class TestLibraryIndexer:
    def test_scan_finds_all_assets(self, lib_root):
        from engine.library import scan_library
        index = scan_library()
        assert index.counts() == {"broll": 3, "music": 2, "sfx": 2}

    def test_rescan_idempotent(self, lib_root):
        from engine.library import scan_library
        index1 = scan_library()
        index2 = scan_library()
        assert index1.counts() == index2.counts()
        assert len(index1.assets) == len(index2.assets)
        for a1, a2 in zip(sorted(index1.assets, key=lambda a: a.filename),
                          sorted(index2.assets, key=lambda a: a.filename)):
            assert a1.filename == a2.filename
            assert a1.tags == a2.tags

    def test_sidecar_tags_loaded(self, lib_root):
        from engine.library import scan_library
        index = scan_library()
        city = next(a for a in index.assets if a.filename == "city_timelapse.mp4")
        assert "city" in city.tags
        assert "urban" in city.tags
        assert city.mood == "energetic"
        assert city.energy == 4

    def test_index_persisted(self, lib_root):
        from engine.library import scan_library, load_index, INDEX_PATH
        scan_library()
        assert INDEX_PATH.is_file()
        loaded = load_index()
        assert loaded.counts() == {"broll": 3, "music": 2, "sfx": 2}

    def test_add_asset(self, lib_root):
        from engine.library import add_asset, load_index
        asset = add_asset("broll", "new_clip.mp4", b"\x00" * 50,
                          tags=["tech", "computer"], mood="neutral")
        assert asset.filename == "new_clip.mp4"
        assert "tech" in asset.tags
        index = load_index()
        assert index.counts()["broll"] == 4

    def test_remove_asset(self, lib_root):
        from engine.library import scan_library, remove_asset, load_index
        scan_library()
        removed = remove_asset("broll", "city_timelapse.mp4")
        assert removed is True
        index = load_index()
        assert index.counts()["broll"] == 2
        assert not (lib_root / "broll" / "city_timelapse.mp4").exists()

    def test_update_tags(self, lib_root):
        from engine.library import scan_library, update_asset_tags, load_index
        scan_library()
        updated = update_asset_tags("broll", "city_timelapse.mp4",
                                     tags=["skyline", "sunset"], mood="warm")
        assert updated is not None
        assert "skyline" in updated.tags
        assert updated.mood == "warm"

    def test_ignores_non_media_files(self, lib_root):
        (lib_root / "broll" / "readme.txt").write_text("not media")
        from engine.library import scan_library
        index = scan_library()
        filenames = [a.filename for a in index.broll]
        assert "readme.txt" not in filenames

    def test_out_of_range_energy_sidecar_does_not_break_scan(self, lib_root):
        """A malformed energy in one sidecar must not crash the whole scan;
        it is coerced to None and the asset still indexes."""
        import yaml
        from engine.library import scan_library
        (lib_root / "music" / "bad_energy.mp3").write_bytes(b"\x00" * 50)
        (lib_root / "music" / "bad_energy.yaml").write_text(
            yaml.dump({"tags": ["calm"], "energy": 99}))
        index = scan_library()  # must not raise
        bad = next(a for a in index.music if a.filename == "bad_energy.mp3")
        assert bad.energy is None
        assert bad.tags == ["calm"]

    def test_update_tags_coerces_bad_energy(self, lib_root):
        from engine.library import scan_library, update_asset_tags, load_index
        scan_library()
        updated = update_asset_tags("music", "calm_piano.mp3", energy=99)
        assert updated is not None
        assert updated.energy is None
        # And the persisted index stays loadable (no out-of-range value stored).
        assert load_index().counts()["music"] == 2


class TestLibraryUploadApi:
    """The upload/update routes reject out-of-range energy with a clean 422
    before touching disk, so a bad value never 500s nor writes an orphan file
    (and never reaches a sidecar that would break the whole index)."""

    def test_validate_energy_rejects_out_of_range(self):
        from fastapi import HTTPException
        from app.routers.music import _validate_energy
        for bad in (0, -1, 6, 99):
            with pytest.raises(HTTPException) as exc:
                _validate_energy(bad)
            assert exc.value.status_code == 422
        # Valid values (and None) pass through without raising.
        for ok in (None, 1, 3, 5):
            _validate_energy(ok)


class TestAssetMatchers:
    def test_broll_match_by_tag(self, lib_root):
        from engine.library import scan_library
        from brain.asset_match import broll_match
        scan_library()
        results = broll_match("city skyline")
        assert len(results) > 0
        assert results[0].filename == "city_timelapse.mp4"

    def test_broll_match_synonym_expansion(self, lib_root):
        from engine.library import scan_library
        from brain.asset_match import broll_match
        scan_library()
        results = broll_match("urban street")
        assert any(r.filename == "city_timelapse.mp4" for r in results)

    def test_broll_match_returns_top_n(self, lib_root):
        from engine.library import scan_library
        from brain.asset_match import broll_match
        scan_library()
        results = broll_match("nature", top_n=2)
        assert len(results) <= 2

    def test_broll_match_fallback_when_no_tags_match(self, lib_root):
        from engine.library import scan_library
        from brain.asset_match import broll_match
        scan_library()
        results = broll_match("xyznonexistent")
        assert len(results) > 0  # falls back to any broll

    def test_music_match_by_mood(self, lib_root):
        from engine.library import scan_library
        from brain.asset_match import music_match
        scan_library()
        results = music_match(mood="calm")
        assert len(results) > 0
        assert results[0].filename == "calm_piano.mp3"

    def test_music_match_by_energy(self, lib_root):
        from engine.library import scan_library
        from brain.asset_match import music_match
        scan_library()
        results = music_match(energy=4)
        assert len(results) > 0
        assert results[0].filename == "upbeat_track.mp3"

    def test_sfx_match_whoosh(self, lib_root):
        from engine.library import scan_library
        from brain.asset_match import sfx_match
        scan_library()
        results = sfx_match("whoosh")
        assert len(results) > 0
        assert results[0].filename == "whoosh_01.wav"

    def test_sfx_match_pop(self, lib_root):
        from engine.library import scan_library
        from brain.asset_match import sfx_match
        scan_library()
        results = sfx_match("pop")
        assert len(results) > 0
        assert results[0].filename == "pop_click.wav"


class TestResolveAssets:
    def test_resolve_broll_query(self, lib_root):
        from engine.library import scan_library
        from brain.asset_match import resolve_plan_assets
        import engine.schema
        engine.schema.PROJECT_ROOT = lib_root.parent
        scan_library()

        plan = {
            "broll": [
                {"at": 2.0, "duration": 2.0, "file": "broll/placeholder.mp4",
                 "query": "city skyline"},
            ],
            "sfx": [],
        }
        resolutions = resolve_plan_assets(plan)
        assert len(resolutions["broll"]) == 1
        assert "city_timelapse" in plan["broll"][0]["file"]

    def test_manual_override_preserved(self, lib_root):
        from engine.library import scan_library
        from brain.asset_match import resolve_plan_assets
        import engine.schema
        engine.schema.PROJECT_ROOT = lib_root.parent
        scan_library()

        # Create a real file at the manual path
        manual_file = lib_root.parent / "my_custom_broll.mp4"
        manual_file.write_bytes(b"\x00" * 50)

        plan = {
            "broll": [
                {"at": 2.0, "duration": 2.0, "file": "my_custom_broll.mp4",
                 "query": "city skyline"},
            ],
            "sfx": [],
        }
        resolve_plan_assets(plan)
        assert plan["broll"][0]["file"] == "my_custom_broll.mp4"
        manual_file.unlink()

    def test_job_local_music_and_sfx_are_not_replaced_by_library_assets(self, lib_root, tmp_path):
        from engine.library import scan_library
        from brain.asset_match import resolve_plan_assets

        scan_library()
        job_dir = tmp_path / "job"
        (job_dir / "music").mkdir(parents=True)
        (job_dir / "sfx").mkdir()
        (job_dir / "music" / "manual.wav").write_bytes(b"music")
        (job_dir / "sfx" / "manual.wav").write_bytes(b"sfx")
        plan = {
            "broll": [],
            "music": {"file": "music/manual.wav", "volume_db": -14, "duck": []},
            "sfx": [{"at": 0.5, "file": "sfx/manual.wav"}],
        }

        resolve_plan_assets(plan, base_dir=job_dir)

        assert plan["music"]["file"] == "music/manual.wav"
        assert plan["sfx"][0]["file"] == "sfx/manual.wav"

    def test_resolution_includes_alternatives(self, lib_root):
        from engine.library import scan_library
        from brain.asset_match import resolve_plan_assets
        import engine.schema
        engine.schema.PROJECT_ROOT = lib_root.parent
        scan_library()

        plan = {
            "broll": [
                {"at": 2.0, "duration": 2.0, "file": "broll/placeholder.mp4",
                 "query": "nature forest"},
            ],
            "sfx": [],
        }
        resolutions = resolve_plan_assets(plan)
        assert len(resolutions["broll"]) == 1
        assert "alternatives" in resolutions["broll"][0]
