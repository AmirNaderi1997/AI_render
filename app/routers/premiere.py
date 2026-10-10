"""Premiere API routes."""
from __future__ import annotations

import json
from typing import Literal
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from engine.premiere import PREMIERE_REPORT
from app import premiere_bridge, premiere_desktop
from app.job_access import verify_job_owner

router = APIRouter(tags=["premiere"])


def _generated(job_id: str, request: Request):
    job = premiere_desktop.job_for_id(job_id)
    verify_job_owner(request, job)
    premiere_desktop.current_identity(job, regenerate=True)
    return job


@router.get("/jobs/{job_id}/premiere")
def download_premiere(job_id: str, request: Request):
    """Build and download an editable Premiere/FCP7 XML package on demand."""
    job = _generated(job_id, request)
    bundle = premiere_desktop.safe_file(job, job.dir / "project_premiere.zip")
    return FileResponse(
        bundle,
        filename=f"ai-render-{job_id}-premiere.zip",
        media_type="application/zip",
    )


@router.get("/integrations/premiere")
def premiere_capability(request: Request):
    result = premiere_desktop.capability()
    try:
        premiere_desktop.require_local(request)
    except HTTPException:
        result['local_launch_supported'] = False
    return result


@router.get("/jobs/{job_id}/premiere/status")
def premiere_desktop_status(job_id: str, request: Request):
    job = premiere_desktop.job_for_id(job_id)
    verify_job_owner(request, job)
    result = premiere_desktop.status(job)
    try:
        premiere_desktop.require_local(request)
    except HTTPException:
        result['capability']['local_launch_supported'] = False
    result['bridge'] = premiere_bridge.status(job)
    # Premiere missing is a normal state, not an error: XML/ZIP export still works.
    available = bool(result['capability']['available'])
    result['available'] = available
    result['message'] = None if available else 'Premiere Pro not detected'
    return result


class PremiereBridgeSessionBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    force_refresh: bool = False


@router.post("/jobs/{job_id}/premiere/bridge/session")
def premiere_bridge_session(job_id: str, request: Request,
                            body: PremiereBridgeSessionBody = PremiereBridgeSessionBody()):
    premiere_desktop.require_local(request)
    job = premiere_desktop.job_for_id(job_id)
    verify_job_owner(request, job)
    return premiere_bridge.create_session(
        job, force_refresh=body.force_refresh)


class PremiereBridgePairBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    pairing_code: str
    bridge: dict = Field(default_factory=dict)


@router.get("/integrations/premiere/bridge/pending")
def premiere_bridge_pending(request: Request):
    """Return the oldest waiting_for_premiere session. Loopback-only."""
    premiere_bridge.require_loopback_peer(request)
    return premiere_bridge.pending()


@router.post("/integrations/premiere/bridge/pair")
def premiere_bridge_pair(body: PremiereBridgePairBody, request: Request):
    premiere_bridge.require_loopback_peer(request)
    return premiere_bridge.pair(body.pairing_code, body.bridge)


@router.get("/integrations/premiere/bridge/debug")
def premiere_bridge_debug(request: Request):
    """Debug endpoint to check active bridge sessions (loopback only)."""
    premiere_bridge.require_loopback_peer(request)
    import time
    now = time.time()
    sessions = []
    for op_id, session in list(premiere_bridge._sessions.items()):
        sessions.append({
            "operation_id": op_id,
            "job_id": session.job_id,
            "state": session.state,
            "created": session.created_at,
            "expires_in_seconds": int(session.expires_at - now),
            "pairing_code_exists": session.pairing_code in premiere_bridge._pairing_codes,
        })
    return {
        "active_sessions": sessions,
        "total_sessions": len(sessions),
        "purge_executed": True,
    }


@router.post("/jobs/{job_id}/premiere/bridge/receipt")
def premiere_bridge_receipt(job_id: str, body: premiere_bridge.PremiereBridgeReceipt,
                            request: Request):
    premiere_bridge.require_loopback_peer(request)
    return premiere_bridge.accept_receipt(
        premiere_desktop.job_for_id(job_id), body.operation_id,
        request.headers.get("authorization"), body)


class PremiereOpenBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    mode: Literal['editable_plan', 'rendered_video', 'plan_and_render', 'saved_project', 'reveal']
    confirm_preview: bool = False


@router.post("/jobs/{job_id}/premiere/open")
def premiere_desktop_open(job_id: str, body: PremiereOpenBody, request: Request):
    premiere_desktop.require_local(request)
    job = premiere_desktop.job_for_id(job_id)
    verify_job_owner(request, job)
    return premiere_desktop.open_mode(
        job, body.mode, confirm_preview=body.confirm_preview)


class PremiereLinkBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    project_name: str


@router.post("/jobs/{job_id}/premiere/link-project")
def premiere_link_project(job_id: str, body: "PremiereLinkBody", request: Request):
    premiere_desktop.require_local(request)
    job = premiere_desktop.job_for_id(job_id)
    verify_job_owner(request, job)
    return premiere_desktop.link_project(job, body.project_name)


@router.get("/jobs/{job_id}/premiere/report")
def premiere_report(job_id: str, request: Request):
    job = _generated(job_id, request)
    report = premiere_desktop.safe_file(job, job.dir / PREMIERE_REPORT)
    return JSONResponse(json.loads(report.read_text(encoding="utf-8")))


@router.get("/jobs/{job_id}/premiere.xml")
def download_premiere_xml(job_id: str, request: Request):
    job = _generated(job_id, request)
    return FileResponse(premiere_desktop.safe_file(job, job.dir / "project_premiere.xml"), filename="project_premiere.xml", media_type="application/xml")


@router.get("/jobs/{job_id}/premiere/captions")
def download_premiere_captions(job_id: str, request: Request):
    job = _generated(job_id, request)
    return FileResponse(premiere_desktop.safe_file(job, job.dir / "premiere_captions.srt"), filename="premiere_captions.srt", media_type="application/x-subrip; charset=utf-8")
