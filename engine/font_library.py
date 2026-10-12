"""Persistent, reviewable font and typography-reference library.

Candidates and approved font files are kept in separate directories. Approval
copies the immutable bytes into the approved library and keys the entry by its
content hash, so plans can refer to it by a stable ID.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

from engine.schema import PROJECT_ROOT


LIBRARY_ROOT = PROJECT_ROOT / "jobs" / "font-library"
CANDIDATES = LIBRARY_ROOT / "candidates"
APPROVED = LIBRARY_ROOT / "approved"
INDEX = LIBRARY_ROOT / "library.json"
MAX_FONT_BYTES = 32 * 1024 * 1024
MAX_IMAGE_BYTES = 20 * 1024 * 1024


def _read() -> dict[str, Any]:
    if not INDEX.exists():
        return {"version": 1, "candidates": [], "approved": []}
    try:
        data = json.loads(INDEX.read_text(encoding="utf-8"))
        if data.get("version") != 1:
            raise ValueError("unsupported font library version")
        return data
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"font library index is unreadable: {exc}") from exc


def _write(data: dict[str, Any]) -> None:
    LIBRARY_ROOT.mkdir(parents=True, exist_ok=True)
    tmp = INDEX.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, INDEX)


def _hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _font_metadata(path: Path) -> dict[str, Any]:
    try:
        from fontTools.ttLib import TTFont
    except ImportError as exc:
        raise RuntimeError("fontTools is required to inspect uploaded font files") from exc
    try:
        font = TTFont(str(path), lazy=False, recalcBBoxes=False, recalcTimestamp=False)
        names = font["name"].names if "name" in font else []

        def get_name(name_id: int) -> str:
            for rec in names:
                if rec.nameID == name_id:
                    try:
                        value = rec.toUnicode().strip()
                        if value:
                            return value
                    except Exception:
                        pass
            return ""

        codepoints: set[int] = set()
        if "cmap" in font:
            for table in font["cmap"].tables:
                codepoints.update(table.cmap)
        # Common Persian alphabet and Persian-specific letters, with Persian
        # digits. Rare Arabic-only letters are not required for Persian support.
        fa_chars = list(range(0x0621, 0x063B)) + list(range(0x0641, 0x064B)) + [0x067E, 0x0686, 0x0698, 0x06A9, 0x06AF,
                                                    0x06CC, 0x06F0, 0x06F1, 0x06F2, 0x06F3,
                                                    0x06F4, 0x06F5, 0x06F6, 0x06F7, 0x06F8,
                                                    0x06F9]
        missing_fa = [f"U+{cp:04X}" for cp in fa_chars if cp not in codepoints]
        latin = set(range(0x20, 0x7F))
        os2 = font.get("OS/2")
        weight = int(getattr(os2, "usWeightClass", 400))
        result = {
            "family": get_name(16) or get_name(1) or path.stem,
            "style": get_name(17) or get_name(2) or "Regular",
            "weight": weight,
            "license": get_name(13) or None,
            "license_url": get_name(14) or None,
            "persian_coverage": {"supported": not missing_fa, "missing": missing_fa},
            "latin_coverage": {"supported": latin.issubset(codepoints),
                               "missing": [f"U+{cp:04X}" for cp in sorted(latin - codepoints)]},
            "glyph_count": len(codepoints),
        }
        font.close()
        return result
    except Exception as exc:
        raise ValueError(f"font file could not be parsed: {exc}") from exc


def list_library() -> dict[str, Any]:
    data = _read()
    # Archived fonts remain resolvable for historical plans, but disappear from
    # the active library and all new-job selectors.
    return {"version": data["version"], "candidates": data["candidates"],
            "approved": [entry for entry in data["approved"] if not entry.get("archived_at")]}


def planner_font_options(persian: bool = False) -> list[dict[str, str]]:
    """List real, renderable project fonts that the planner may select.

    Bundled font names come from the font files themselves. Approved library
    fonts are included by stable id so the model cannot invent font families.
    """
    options: list[dict[str, str]] = []
    bundled_dir = PROJECT_ROOT / "presets" / "fonts"
    seen: set[tuple[str, str | None]] = set()
    for path in sorted(bundled_dir.rglob("*")):
        if path.suffix.lower() not in {".ttf", ".otf", ".ttc"}:
            continue
        try:
            metadata = _font_metadata(path)
        except (RuntimeError, ValueError):
            continue
        if persian and not metadata["persian_coverage"]["supported"]:
            continue
        family = metadata["family"]
        if family.casefold() == "ray":
            from .captions import render_font_family
            family = render_font_family(path.stem)
        key = (family, None)
        if key in seen:
            continue
        seen.add(key)
        options.append({"family": family, "style": metadata["style"]})

    for entry in list_library()["approved"]:
        if entry.get("kind") != "font_file":
            continue
        metadata = entry.get("metadata") or {}
        if persian and not metadata.get("persian_coverage", {}).get("supported", False):
            continue
        key = (str(entry.get("family", "")), str(entry.get("id", "")))
        if key in seen:
            continue
        seen.add(key)
        options.append({"family": key[0], "style": str(entry.get("style", "Regular")),
                        "caption_font_id": key[1]})
    return options


def render_font_path(canvas) -> Path | None:
    """Resolve the selected family to a file so renderers load its glyphs."""
    if canvas.caption_font_id:
        return Path(resolve_font(canvas.caption_font_id)["path"])
    family = canvas.caption_font
    if not family:
        return None
    from .captions import render_font_family
    for path in sorted((PROJECT_ROOT / "presets" / "fonts").rglob("*")):
        if path.suffix.lower() not in {".ttf", ".otf", ".ttc"}:
            continue
        try:
            metadata_family = _font_metadata(path)["family"]
            face_family = render_font_family(path.stem) if metadata_family.casefold() == "ray" else metadata_family
            if face_family.casefold() == family.casefold():
                return path.resolve()
        except (RuntimeError, ValueError):
            continue
    return None


def list_approved_files() -> list[Path]:
    data = _read()
    result = []
    for entry in data["approved"]:
        if entry.get("kind") == "font_file":
            path = APPROVED / entry["filename"]
            if path.is_file() and _hash(path) == entry.get("sha256"):
                result.append(path.resolve())
    return result


def get_approved(font_id: str) -> dict[str, Any] | None:
    for entry in _read()["approved"]:
        if entry.get("id") == font_id:
            return entry
    return None


def add_text_reference(name: str, copied_text: str, font_name: str = "",
                       visual_reference: str = "") -> dict[str, Any]:
    if not name.strip() or not copied_text.strip():
        raise ValueError("a reference name and copied text are required")
    data = _read()
    item = {"id": "cand_" + uuid.uuid4().hex[:16], "kind": "text_reference",
            "name": name.strip(), "font_name": font_name.strip() or None,
            "copied_text": copied_text[:4000], "visual_reference": visual_reference.strip() or None,
            "source": {"type": "copied_text"}, "review_state": "candidate"}
    data["candidates"].append(item)
    _write(data)
    return item


def add_image_reference(filename: str, content: bytes) -> dict[str, Any]:
    if not content or len(content) > MAX_IMAGE_BYTES:
        raise ValueError("image must be non-empty and at most 20 MB")
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(content))
        img.verify()
    except Exception as exc:
        raise ValueError(f"invalid image file: {exc}") from exc
    CANDIDATES.mkdir(parents=True, exist_ok=True)
    candidate_id = "cand_" + uuid.uuid4().hex[:16]
    ext = Path(filename).suffix.lower()
    if ext not in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}:
        ext = ".img"
    path = CANDIDATES / f"{candidate_id}{ext}"
    path.write_bytes(content)
    try:
        installed = subprocess.run(["tesseract", "--list-langs"], capture_output=True,
                                   text=True, timeout=10)
        available = set((installed.stdout or "").splitlines()) if installed.returncode == 0 else set()
        used_language = "fas+eng" if "fas" in available else "eng"
        proc = subprocess.run(["tesseract", str(path), "stdout", "-l", used_language],
                              capture_output=True, text=True, timeout=30)
        if proc.returncode and used_language != "eng":
            used_language = "eng"
            proc = subprocess.run(["tesseract", str(path), "stdout", "-l", "eng"],
                                  capture_output=True, text=True, timeout=30)
        extracted = proc.stdout.strip() if proc.returncode == 0 else ""
        if extracted and used_language == "eng":
            ocr_note = "Tesseract OCR English fallback; Persian trained data is unavailable"
        elif extracted:
            ocr_note = "Tesseract OCR Persian and English"
        else:
            ocr_note = "OCR returned no text; edit the extracted text manually"
    except (OSError, subprocess.TimeoutExpired) as exc:
        extracted, ocr_note = "", f"OCR unavailable: {exc}"
    data = _read()
    # Image evidence cannot identify a typeface. Offer a short, explicitly
    # unranked list of available families for human comparison.
    families = set()
    for font_path in (PROJECT_ROOT / "presets" / "fonts").rglob("*"):
        if font_path.is_file() and font_path.suffix.lower() in {".ttf", ".otf"}:
            try:
                families.add(_font_metadata(font_path)["family"])
            except Exception:
                continue
    approximate = sorted(families)[:8]
    approximate.extend(e["family"] for e in data["approved"]
                       if e.get("kind") == "font_file" and e["family"] not in approximate)
    item = {"id": candidate_id, "kind": "image_reference", "name": Path(filename).name,
            "filename": path.name, "sha256": _hash(path), "extracted_text": extracted,
            "ocr_note": ocr_note,
            "font_candidates": [{"family": f, "confidence": "approximate", "basis":
                                 "human comparison required; image pixels do not prove identity"}
                                for f in approximate],
            "source": {"type": "image", "original_name": Path(filename).name},
            "review_state": "candidate"}
    data["candidates"].append(item)
    _write(data)
    return item


def add_font_file(filename: str, content: bytes) -> dict[str, Any]:
    ext = Path(filename).suffix.lower()
    if ext not in {".ttf", ".otf"}:
        raise ValueError("only .ttf and .otf files are accepted")
    if not content or len(content) > MAX_FONT_BYTES:
        raise ValueError("font file must be non-empty and at most 32 MB")
    CANDIDATES.mkdir(parents=True, exist_ok=True)
    candidate_id = "cand_" + uuid.uuid4().hex[:16]
    path = CANDIDATES / f"{candidate_id}{ext}"
    path.write_bytes(content)
    try:
        metadata = _font_metadata(path)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    data = _read()
    item = {"id": candidate_id, "kind": "font_file", "name": Path(filename).name,
            "filename": path.name, "sha256": _hash(path), "metadata": metadata,
            "source": {"type": "upload", "original_name": Path(filename).name},
            "review_state": "candidate"}
    data["candidates"].append(item)
    _write(data)
    return item


def approve(candidate_id: str) -> dict[str, Any]:
    data = _read()
    candidate = next((e for e in data["candidates"] if e["id"] == candidate_id), None)
    if not candidate:
        raise KeyError("candidate not found")
    if candidate["kind"] != "font_file":
        raise ValueError("typography references can be saved for review but cannot be used as fonts")
    source = CANDIDATES / candidate["filename"]
    digest = _hash(source)
    if digest != candidate["sha256"]:
        raise ValueError("candidate font changed after inspection; import it again")
    font_id = "font_" + digest[:20]
    existing = next((e for e in data["approved"] if e["id"] == font_id), None)
    if existing:
        # Re-importing identical bytes is the explicit restore path for a font
        # that was previously removed from the active library.
        existing.pop("archived_at", None)
        data["candidates"].remove(candidate)
        _write(data)
        source.unlink(missing_ok=True)
        return existing
    APPROVED.mkdir(parents=True, exist_ok=True)
    filename = f"{font_id}{source.suffix.lower()}"
    dest = APPROVED / filename
    shutil.copy2(source, dest)
    entry = {"id": font_id, "kind": "font_file", "family": candidate["metadata"]["family"],
             "style": candidate["metadata"]["style"], "metadata": candidate["metadata"],
             "filename": filename, "sha256": digest, "source": candidate["source"],
             "review_state": "approved"}
    data["approved"].append(entry)
    data["candidates"].remove(candidate)
    _write(data)
    source.unlink(missing_ok=True)
    return entry


def remove(entry_id: str) -> dict[str, Any]:
    """Remove a candidate or archive an approved font.

    Approved bytes are deliberately retained so existing job plans remain
    reproducible. They are hidden from active library listings and can be
    restored by importing the same file again.
    """
    data = _read()
    candidate = next((entry for entry in data["candidates"] if entry["id"] == entry_id), None)
    if candidate:
        data["candidates"].remove(candidate)
        filename = candidate.get("filename")
        if filename:
            (CANDIDATES / Path(filename).name).unlink(missing_ok=True)
        _write(data)
        return {"ok": True, "id": entry_id, "state": "deleted"}

    approved = next((entry for entry in data["approved"] if entry["id"] == entry_id), None)
    if not approved:
        raise KeyError("font library item not found")
    if not approved.get("archived_at"):
        approved["archived_at"] = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat()
        _write(data)
    return {"ok": True, "id": entry_id, "state": "archived"}


def resolve_font(font_id: str) -> dict[str, Any]:
    entry = get_approved(font_id)
    if not entry or entry.get("kind") != "font_file":
        raise ValueError(f"selected font {font_id!r} is missing or not approved")
    path = APPROVED / entry["filename"]
    if not path.is_file() or _hash(path) != entry.get("sha256"):
        raise ValueError(f"selected font {font_id!r} is missing or its content hash changed")
    return {**entry, "path": path.resolve()}


def family_for_plan(canvas) -> str | None:
    if not canvas.caption_font_id:
        return canvas.caption_font
    return str(resolve_font(canvas.caption_font_id)["family"])


def stage_for_job(font_id: str, job_dir: Path) -> dict[str, Any]:
    """Copy the selected approved font beside job exports for portability."""
    entry = resolve_font(font_id)
    job_dir = Path(job_dir).resolve()
    relative = Path("assets") / "fonts" / entry["filename"]
    destination = job_dir / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists() or _hash(destination) != entry["sha256"]:
        shutil.copy2(entry["path"], destination)
    return {**entry, "job_path": destination, "job_relative_path": relative.as_posix()}
