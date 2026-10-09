"""Asset library indexer for B-roll, music, and SFX.

Scans assets/{broll,music,sfx}/ folders, reads optional YAML sidecar files
for tags/metadata, and maintains a JSON index for fast lookup by matchers.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from . import schema as _schema

log = logging.getLogger(__name__)

LIBRARY_ROOT = _schema.PROJECT_ROOT / "assets"
INDEX_PATH = LIBRARY_ROOT / "library_index.json"

MEDIA_EXTENSIONS = {
    "video": {".mp4", ".mov", ".webm", ".mkv", ".avi"},
    "audio": {".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac"},
    "image": {".jpg", ".jpeg", ".png", ".webp", ".gif"},
}
ALL_MEDIA = MEDIA_EXTENSIONS["video"] | MEDIA_EXTENSIONS["audio"] | MEDIA_EXTENSIONS["image"]

AssetCategory = Literal["broll", "music", "sfx"]
CATEGORIES: list[AssetCategory] = ["broll", "music", "sfx"]


class LibraryAsset(BaseModel):
    filename: str
    category: AssetCategory
    path: str
    tags: list[str] = []
    mood: Optional[str] = None
    energy: Optional[int] = Field(default=None, ge=1, le=5)
    duration_sec: Optional[float] = None
    description: Optional[str] = None


class LibraryIndex(BaseModel):
    version: int = 1
    assets: list[LibraryAsset] = []

    @property
    def broll(self) -> list[LibraryAsset]:
        return [a for a in self.assets if a.category == "broll"]

    @property
    def music(self) -> list[LibraryAsset]:
        return [a for a in self.assets if a.category == "music"]

    @property
    def sfx(self) -> list[LibraryAsset]:
        return [a for a in self.assets if a.category == "sfx"]

    def counts(self) -> dict[str, int]:
        return {cat: sum(1 for a in self.assets if a.category == cat)
                for cat in CATEGORIES}


def _read_sidecar(media_path: Path) -> dict:
    """Read a YAML sidecar file (<name>.yaml or <name>.yml) next to a media file."""
    import yaml
    for ext in (".yaml", ".yml"):
        sidecar = media_path.with_suffix(ext)
        if sidecar.is_file():
            try:
                return yaml.safe_load(sidecar.read_text()) or {}
            except Exception as exc:
                log.warning("bad sidecar %s: %s", sidecar, exc)
    return {}


def _clean_energy(value) -> Optional[int]:
    """Coerce a sidecar/index energy value into the 1-5 range LibraryAsset
    allows, dropping anything invalid to None so a bad value can never crash
    indexing for the entire library."""
    try:
        energy = int(value)
    except (TypeError, ValueError):
        return None
    return energy if 1 <= energy <= 5 else None


def _probe_duration_safe(path: Path) -> Optional[float]:
    try:
        from .probe import probe_duration
        return round(probe_duration(path), 2)
    except Exception:
        return None


def scan_category(category: AssetCategory) -> list[LibraryAsset]:
    """Scan one asset folder and return indexed assets."""
    folder = LIBRARY_ROOT / category
    if not folder.is_dir():
        return []
    assets: list[LibraryAsset] = []
    for f in sorted(folder.iterdir()):
        if not f.is_file() or f.suffix.lower() not in ALL_MEDIA:
            continue
        sidecar = _read_sidecar(f)
        duration = _probe_duration_safe(f) if f.suffix.lower() in (MEDIA_EXTENSIONS["video"] | MEDIA_EXTENSIONS["audio"]) else None
        try:
            assets.append(LibraryAsset(
                filename=f.name,
                category=category,
                path=str(f.relative_to(LIBRARY_ROOT.parent)),
                tags=[str(t).lower().strip() for t in sidecar.get("tags", [])],
                mood=sidecar.get("mood"),
                energy=_clean_energy(sidecar.get("energy")),
                duration_sec=duration,
                description=sidecar.get("description"),
            ))
        except Exception as exc:
            # One malformed sidecar must not take down the whole library listing.
            log.warning("skipping un-indexable asset %s: %s", f, exc)
    return assets


def scan_library() -> LibraryIndex:
    """Full rescan of all asset categories. Returns and persists the index."""
    assets: list[LibraryAsset] = []
    for cat in CATEGORIES:
        assets.extend(scan_category(cat))
    index = LibraryIndex(assets=assets)
    save_index(index)
    log.info("library scan: %s", index.counts())
    return index


def load_index() -> LibraryIndex:
    """Load the persisted index, or rescan if missing."""
    if INDEX_PATH.is_file():
        try:
            data = json.loads(INDEX_PATH.read_text())
            return LibraryIndex(**data)
        except Exception as exc:
            log.warning("corrupt library index, rescanning: %s", exc)
    return scan_library()


def save_index(index: LibraryIndex) -> None:
    LIBRARY_ROOT.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(index.model_dump(), indent=2, ensure_ascii=False))


def add_asset(category: AssetCategory, filename: str, data: bytes,
              tags: list[str] | None = None, mood: str | None = None,
              energy: int | None = None, description: str | None = None) -> LibraryAsset:
    """Save an uploaded file into the library and update the index."""
    folder = LIBRARY_ROOT / category
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / Path(filename).name
    dest.write_bytes(data)

    if tags or mood or energy or description:
        import yaml
        sidecar = {}
        if tags:
            sidecar["tags"] = tags
        if mood:
            sidecar["mood"] = mood
        if energy is not None:
            sidecar["energy"] = energy
        if description:
            sidecar["description"] = description
        dest.with_suffix(".yaml").write_text(
            yaml.dump(sidecar, allow_unicode=True, default_flow_style=False))

    duration = _probe_duration_safe(dest) if dest.suffix.lower() in (MEDIA_EXTENSIONS["video"] | MEDIA_EXTENSIONS["audio"]) else None
    asset = LibraryAsset(
        filename=dest.name,
        category=category,
        path=str(dest.relative_to(LIBRARY_ROOT.parent)),
        tags=[t.lower().strip() for t in (tags or [])],
        mood=mood,
        energy=energy,
        duration_sec=duration,
        description=description,
    )

    index = load_index()
    index.assets = [a for a in index.assets
                    if not (a.category == category and a.filename == dest.name)]
    index.assets.append(asset)
    save_index(index)
    return asset


def remove_asset(category: AssetCategory, filename: str) -> bool:
    """Remove an asset file and its sidecar, update the index."""
    folder = LIBRARY_ROOT / category
    target = folder / filename
    removed = False
    if target.is_file():
        target.unlink()
        removed = True
    for ext in (".yaml", ".yml"):
        sc = target.with_suffix(ext)
        if sc.is_file():
            sc.unlink()
    index = load_index()
    index.assets = [a for a in index.assets
                    if not (a.category == category and a.filename == filename)]
    save_index(index)
    return removed


def update_asset_tags(category: AssetCategory, filename: str,
                      tags: list[str] | None = None, mood: str | None = None,
                      energy: int | None = None, description: str | None = None) -> Optional[LibraryAsset]:
    """Update sidecar metadata for an existing asset."""
    import yaml
    folder = LIBRARY_ROOT / category
    target = folder / filename
    if not target.is_file():
        return None
    sidecar = _read_sidecar(target)
    if tags is not None:
        sidecar["tags"] = tags
    if mood is not None:
        sidecar["mood"] = mood
    if energy is not None:
        sidecar["energy"] = energy
    if description is not None:
        sidecar["description"] = description
    target.with_suffix(".yaml").write_text(
        yaml.dump(sidecar, allow_unicode=True, default_flow_style=False))

    index = load_index()
    for asset in index.assets:
        if asset.category == category and asset.filename == filename:
            asset.tags = [t.lower().strip() for t in sidecar.get("tags", [])]
            asset.mood = sidecar.get("mood")
            asset.energy = _clean_energy(sidecar.get("energy"))
            asset.description = sidecar.get("description")
            save_index(index)
            return asset
    return None


def library_for_api() -> dict:
    """Return the library index formatted for the API."""
    index = load_index()
    return {
        "counts": index.counts(),
        "assets": [a.model_dump() for a in index.assets],
    }
