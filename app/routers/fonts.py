"""Fonts API routes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel
from engine.schema import PROJECT_ROOT

router = APIRouter(prefix="/fonts", tags=["fonts"])
legacy_router = APIRouter(tags=["fonts"])


@router.get("")
def list_fonts():
    from engine.captions import fonts_dir, load_style
    directory = fonts_dir(load_style("rafiei_reel")) or PROJECT_ROOT / "presets" / "fonts"
    names = ({p.stem for p in directory.rglob("*")
              if p.is_file() and p.suffix.lower() in {".ttf", ".otf"}}
             if directory.is_dir() else set())
    from engine.font_library import list_library
    names.update(e["family"] for e in list_library()["approved"] if e.get("kind") == "font_file")
    return {"fonts": sorted(names)}


@legacy_router.get("/font-library")
def get_font_library():
    from engine.font_library import list_library
    return list_library()


class FontTextReference(BaseModel):
    name: str
    copied_text: str
    font_name: str = ""
    visual_reference: str = ""


@legacy_router.post("/font-library/text")
def save_font_text_reference(body: FontTextReference):
    from engine.font_library import add_text_reference
    try:
        return add_text_reference(body.name, body.copied_text, body.font_name, body.visual_reference)
    except ValueError as e:
        raise HTTPException(422, str(e))


@legacy_router.post("/font-library/image")
async def import_font_image(image: UploadFile = File(...)):
    from engine.font_library import add_image_reference
    try:
        return add_image_reference(image.filename or "reference.png", await image.read())
    except ValueError as e:
        raise HTTPException(422, str(e))


@legacy_router.post("/font-library/font")
async def import_font_file(font: UploadFile = File(...)):
    from engine.font_library import add_font_file
    try:
        return add_font_file(font.filename or "font.ttf", await font.read())
    except ValueError as e:
        raise HTTPException(422, str(e))
    except RuntimeError as e:
        raise HTTPException(503, str(e))


@legacy_router.post("/font-library/{candidate_id}/approve")
def approve_font(candidate_id: str):
    from engine.font_library import approve
    try:
        return approve(candidate_id)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))


@legacy_router.delete("/font-library/{entry_id}")
def delete_font_library_item(entry_id: str):
    from engine.font_library import remove
    try:
        return remove(entry_id)
    except KeyError as e:
        raise HTTPException(404, str(e))


@legacy_router.get("/font-library/fonts/{font_id}/file")
def get_approved_font_file(font_id: str):
    from engine.font_library import resolve_font
    try:
        font = resolve_font(font_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return FileResponse(font["path"], filename=font["filename"])


@legacy_router.get("/font-library/candidates/{candidate_id}/file")
def get_candidate_font_file(candidate_id: str):
    from engine.font_library import CANDIDATES, list_library
    candidate = next((e for e in list_library()["candidates"]
                      if e["id"] == candidate_id and e.get("kind") == "font_file"), None)
    if not candidate:
        raise HTTPException(404, "font candidate not found")
    path = CANDIDATES / candidate["filename"]
    if not path.is_file():
        raise HTTPException(404, "font candidate file is missing")
    return FileResponse(path, filename=path.name)
