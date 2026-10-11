"""Content API routes."""
from __future__ import annotations

import json
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from app import jobs as jobstore
from app.job_access import get_job_for_request

router = APIRouter(prefix="/content", tags=["content"])
legacy_router = APIRouter(tags=["content"])


class ContentCreateBody(BaseModel):
    prompt: str
    content_type: str = "reel"
    language: str = "fa"
    style: str = "rafiei_reel"
    provider: str = "local_fixture"
    creative_brief: dict[str, str] = Field(default_factory=dict)


class StoryboardUpdateBody(BaseModel):
    scenes: list[dict]


class StoryboardApproveBody(BaseModel):
    provider: str | None = None


@router.post("/create")
def content_create(body: ContentCreateBody, request: Request):
    from brain.content_creator import create_content
    try:
        result = create_content(
            prompt=body.prompt,
            content_type=body.content_type,
            language=body.language,
            style=body.style,
            provider_name=body.provider,
            creative_brief=body.creative_brief,
            user_id=str(request.state.user.id),
        )
    except (KeyError, ValueError) as e:
        raise HTTPException(422, str(e))
    return result


@legacy_router.get("/jobs/{job_id}/storyboard")
def get_storyboard(job_id: str, request: Request):
    job = get_job_for_request(request, job_id)
    sb_path = job.dir / "storyboard.json"
    if not sb_path.exists():
        raise HTTPException(404, "storyboard not found")
    return json.loads(sb_path.read_text())


@legacy_router.put("/jobs/{job_id}/storyboard")
def update_storyboard(job_id: str, body: StoryboardUpdateBody, request: Request):
    job = get_job_for_request(request, job_id)
    from brain.content_creator import update_storyboard as _update_sb
    try:
        return _update_sb(job, body.scenes)
    except ValueError as e:
        raise HTTPException(422, str(e))


@legacy_router.post("/jobs/{job_id}/storyboard/approve")
def approve_storyboard(job_id: str, request: Request, body: StoryboardApproveBody | None = None):
    job = get_job_for_request(request, job_id)
    sb_path = job.dir / "storyboard.json"
    if not sb_path.exists():
        raise HTTPException(400, "no storyboard to approve")
    from brain.content_creator import approve_and_generate
    try:
        approve_and_generate(job, provider_name=body.provider if body else None)
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e))
    return {"status": "generating"}


@legacy_router.get("/jobs/{job_id}/storyboard/status")
def storyboard_status(job_id: str, request: Request):
    job = get_job_for_request(request, job_id)
    from brain.content_creator import get_storyboard_status
    return get_storyboard_status(job)


@router.get("/providers")
def content_providers():
    from brain.content_creator import list_providers
    return list_providers()


@router.post("/export-image/{job_id}")
def export_content_image(job_id: str, request: Request):
    job = get_job_for_request(request, job_id)
    gen_dir = job.dir / "generated"
    if not gen_dir.is_dir():
        raise HTTPException(404, "no generated media")
    images = sorted(gen_dir.glob("*.png")) + sorted(gen_dir.glob("*.jpg"))
    if not images:
        raise HTTPException(404, "no image export available")
    return FileResponse(images[0], filename=images[0].name)
