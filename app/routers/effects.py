"""Effects API routes."""
from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from engine.effects_v4 import catalog_for_api
from app import jobs as jobstore
from app.job_access import get_job_for_request

router = APIRouter(tags=["effects"])


@router.get("/effects")
def list_effects():
    return catalog_for_api()


@router.get("/rafiei-styles")
def get_rafiei_styles():
    from engine.captions import load_style
    style = load_style("rafiei_reel").get("rafiei_style", {})
    return {key: style.get(key) for key in (
        "preferred_effects", "avoid_effects", "caption_emphasis_color",
        "caption_emphasis_alt_color", "opening_title", "watermark", "credit_lower_third")}


@router.get("/my-effects")
def get_my_effects():
    """Get current My Effects preferences (favorites, rules, dislikes, custom assets)."""
    from engine.effects_v4 import MyEffectsPreset
    my_effects = MyEffectsPreset()
    return {
        "favorites": my_effects.favorites,
        "rules": my_effects.rules,
        "dislikes": list(my_effects.dislikes),
        "custom_assets": my_effects.custom_assets,
        "selected_rafiei_style": my_effects.selected_rafiei_style,
    }


class MyEffectsBody(BaseModel):
    favorites: dict = {}
    rules: list = []
    dislikes: list = []
    custom_assets: dict = {}
    selected_rafiei_style: Optional[str] = None


@router.put("/my-effects")
def put_my_effects(body: MyEffectsBody):
    """Save My Effects preferences."""
    from engine.effects_v4 import MyEffectsPreset
    my_effects = MyEffectsPreset()
    my_effects.favorites = body.favorites
    my_effects.rules = body.rules
    my_effects.dislikes = set(body.dislikes)
    my_effects.custom_assets = body.custom_assets
    my_effects.selected_rafiei_style = body.selected_rafiei_style
    my_effects.save()
    return {"ok": True}


class RafieiStyleSelection(BaseModel):
    style_id: Optional[str] = None


@router.post("/my-effects/select-rafiei")
def select_rafiei_style(body: RafieiStyleSelection):
    from engine.captions import load_style
    from engine.effects_v4 import MyEffectsPreset
    style = load_style("rafiei_reel")["rafiei_style"]
    if body.style_id is not None and body.style_id not in style["preferred_effects"]:
        raise HTTPException(422, "unknown Rafiei style")
    my = MyEffectsPreset()
    my.selected_rafiei_style = body.style_id
    my.save()
    return {"ok": True, "selected_rafiei_style": body.style_id}


@router.get("/jobs/{job_id}/effect-feedback")
def get_effect_feedback(job_id: str, request: Request):
    """Get effect feedback examples (user edits for learning)."""
    get_job_for_request(request, job_id)
    from engine.effects_v4 import EffectFeedback
    feedback = EffectFeedback()
    return {"examples": feedback.examples}


class EffectFeedbackBody(BaseModel):
    segment_text: str
    role: str
    old_effect: str
    new_effect: str


@router.post("/jobs/{job_id}/effect-feedback")
def post_effect_feedback(job_id: str, body: EffectFeedbackBody, request: Request):
    """Log an effect edit for learning."""
    get_job_for_request(request, job_id)
    from engine.effects_v4 import EffectFeedback
    feedback = EffectFeedback()
    feedback.add(body.segment_text, body.role, body.old_effect, body.new_effect)
    return {"ok": True, "total_examples": len(feedback.examples)}
