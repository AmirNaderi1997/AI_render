"""Tag-based asset matchers for B-roll, music, and SFX.

Matches library assets to plan queries using tag overlap, mood/energy
proximity, and duration constraints. No embeddings yet — pure tag matching.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

from engine.library import LibraryAsset, load_index

log = logging.getLogger(__name__)

# Common Persian/English synonyms to expand queries
_SYNONYMS: dict[str, list[str]] = {
    "city": ["urban", "street", "building", "شهر"],
    "nature": ["tree", "forest", "green", "طبیعت", "جنگل"],
    "office": ["desk", "computer", "work", "اداره", "دفتر"],
    "money": ["cash", "dollar", "finance", "پول"],
    "phone": ["mobile", "smartphone", "گوشی", "موبایل"],
    "happy": ["joy", "smile", "خوشحال", "شاد"],
    "sad": ["crying", "tears", "غمگین"],
    "tech": ["technology", "digital", "code", "تکنولوژی"],
    "food": ["cooking", "restaurant", "غذا"],
    "car": ["driving", "road", "ماشین"],
    "people": ["crowd", "person", "مردم"],
    "business": ["meeting", "corporate", "کسب و کار"],
    "success": ["win", "achievement", "موفقیت"],
    "whoosh": ["transition", "swoosh"],
    "pop": ["click", "notification"],
    "ding": ["bell", "alert"],
}


def _tokenize(text: str) -> set[str]:
    """Split text into lowercase tokens, stripping punctuation."""
    return {w.strip() for w in re.split(r'[\s,;/+\-_|.]+', text.lower()) if w.strip()}


def _expand_query(query: str) -> set[str]:
    """Expand a query with synonym variants."""
    tokens = _tokenize(query)
    expanded = set(tokens)
    for token in tokens:
        for key, synonyms in _SYNONYMS.items():
            if token == key or token in synonyms:
                expanded.add(key)
                expanded.update(synonyms)
    return expanded


def _tag_score(asset: LibraryAsset, query_tokens: set[str]) -> float:
    """Score an asset against query tokens. Higher = better match."""
    asset_tokens = set(asset.tags)
    if asset.description:
        asset_tokens.update(_tokenize(asset.description))
    if asset.mood:
        asset_tokens.add(asset.mood.lower())

    if not asset_tokens:
        return 0.0

    overlap = asset_tokens & query_tokens
    if not overlap:
        return 0.0

    return len(overlap) / max(len(query_tokens), 1)


def broll_match(query: str, min_duration: float = 0.0, top_n: int = 3) -> list[LibraryAsset]:
    """Find B-roll assets matching a text query.

    Returns up to top_n assets sorted by relevance, filtered by min_duration.
    """
    index = load_index()
    candidates = index.broll

    if min_duration > 0:
        candidates = [a for a in candidates
                      if a.duration_sec is None or a.duration_sec >= min_duration]

    query_tokens = _expand_query(query)
    scored = [(a, _tag_score(a, query_tokens)) for a in candidates]
    scored = [(a, s) for a, s in scored if s > 0]
    scored.sort(key=lambda x: -x[1])

    results = [a for a, _ in scored[:top_n]]

    if not results and candidates:
        results = candidates[:top_n]
        log.debug("broll_match: no tag match for %r, returning first %d", query, len(results))

    return results


def music_match(mood: Optional[str] = None, energy: Optional[int] = None,
                top_n: int = 1) -> list[LibraryAsset]:
    """Find music assets matching mood and energy.

    Returns up to top_n assets. Falls back to any available music if no match.
    """
    index = load_index()
    candidates = index.music

    if not candidates:
        return []

    scored: list[tuple[LibraryAsset, float]] = []
    for asset in candidates:
        score = 0.0
        if mood and asset.mood and asset.mood.lower() == mood.lower():
            score += 2.0
        if mood and asset.tags:
            mood_tokens = _tokenize(mood)
            tag_overlap = set(asset.tags) & mood_tokens
            score += len(tag_overlap) * 0.5
        if energy is not None and asset.energy is not None:
            score += max(0, 2.0 - abs(energy - asset.energy) * 0.5)
        scored.append((asset, score))

    scored.sort(key=lambda x: -x[1])
    results = [a for a, _ in scored[:top_n]]
    return results if results else candidates[:top_n]


def sfx_match(category: str, top_n: int = 1) -> list[LibraryAsset]:
    """Find SFX assets matching a category (e.g. 'whoosh', 'pop', 'ding').

    Returns up to top_n assets.
    """
    index = load_index()
    candidates = index.sfx

    if not candidates:
        return []

    query_tokens = _expand_query(category)
    scored = [(a, _tag_score(a, query_tokens)) for a in candidates]
    scored.sort(key=lambda x: -x[1])

    results = [a for a, s in scored[:top_n] if s > 0]
    return results if results else candidates[:top_n]


def resolve_plan_assets(plan_data: dict, base_dir: Optional[Path] = None) -> dict:
    """Resolve unresolved broll queries and missing music/sfx in a plan.

    Mutates plan_data in place. Returns a summary of resolutions.
    Resolves assets that have a query but no valid file, or a placeholder file.
    Preserves existing user-specified paths and omits unresolved missing media.
    """
    from engine.schema import PROJECT_ROOT

    base = Path(base_dir) if base_dir is not None else PROJECT_ROOT

    def exists(path_text: str) -> bool:
        if not path_text:
            return False
        path = Path(path_text)
        if path.is_absolute():
            return path.is_file()
        return (base / path).is_file() or (PROJECT_ROOT / path).is_file()

    resolutions: dict = {"broll": [], "omitted_broll": [], "music": None, "sfx": []}

    retained_broll = []
    for i, broll in enumerate(plan_data.get("broll", [])):
        query = broll.get("query")
        file_path = broll.get("file", "")
        is_placeholder = not file_path or "placeholder" in file_path.lower()
        file_exists = exists(file_path)

        if query and (is_placeholder or not file_exists):
            min_dur = float(broll.get("duration", 0))
            try:
                matches = broll_match(query, min_duration=min_dur, top_n=3)
            except Exception as exc:
                log.warning("B-roll lookup failed for item %d: %s", i, exc)
                matches = []
            match = next((candidate for candidate in matches if exists(candidate.path)), None)
            if match:
                broll["file"] = match.path
                alternatives = [m.path for m in matches if m.path != match.path and exists(m.path)]
                resolutions["broll"].append({
                    "index": len(retained_broll),
                    "query": query,
                    "matched": match.path,
                    "alternatives": alternatives,
                })

        resolved_file = broll.get("file", "")
        if not resolved_file or "placeholder" in resolved_file.lower() or not exists(resolved_file):
            resolutions["omitted_broll"].append({
                "index": i,
                "query": query,
                "file": file_path,
                "reason": "no existing B-roll media was available",
            })
            log.warning("omitted B-roll item %d because no existing media was available: %s", i, file_path)
            continue
        retained_broll.append(broll)

    plan_data["broll"] = retained_broll

    if not plan_data.get("music") or not plan_data["music"].get("file"):
        pass
    elif plan_data.get("music"):
        music_file = plan_data["music"].get("file", "")
        if music_file and not exists(music_file):
            matches = music_match(top_n=1)
            if matches:
                plan_data["music"]["file"] = matches[0].path
                resolutions["music"] = {"matched": matches[0].path}

    for i, sfx in enumerate(plan_data.get("sfx", [])):
        sfx_file = sfx.get("file", "")
        if sfx_file and not exists(sfx_file):
            matches = sfx_match("whoosh", top_n=1)
            if matches:
                sfx["file"] = matches[0].path
                resolutions["sfx"].append({
                    "index": i,
                    "matched": matches[0].path,
                })

    plan_data["_asset_resolutions"] = resolutions
    return resolutions
