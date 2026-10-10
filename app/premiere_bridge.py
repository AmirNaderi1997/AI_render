"""Authenticated command/receipt protocol for an in-Premiere bridge.

The bridge is deliberately transport-agnostic.  The current Premiere 25.3 host
uses a CEP panel; a future UXP panel can use the same HTTP contract.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, ValidationError
from typing_extensions import Literal

from engine.premiere import PREMIERE_CAPTIONS, PREMIERE_XML
from . import premiere_desktop
from . import jobs as jobstore


SESSION_TTL_SECONDS = 15 * 60
RECEIPT_FILE = "premiere_bridge_receipt.json"
BRIDGE_PROTOCOL_VERSION = 1


class ArtifactIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    plan_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    xml_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    srt_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    render_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    project_path: StrictStr = Field(min_length=1)


class ProjectObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    requested_path: StrictStr = Field(min_length=1)
    active_path: StrictStr = Field(min_length=1)
    opened: StrictBool
    saved: StrictBool


class SequenceObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: StrictStr = Field(min_length=1)
    sequence_id: StrictStr = Field(min_length=1)
    imported: StrictBool
    timeline_open: StrictBool
    video_track_count: StrictInt = Field(ge=0)
    audio_track_count: StrictInt = Field(ge=0)


class MediaObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    media_path: StrictStr = Field(min_length=1)
    imported: StrictBool
    placed_on_editable_timeline: StrictBool


class CaptionObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    media_path: StrictStr = Field(min_length=1)
    imported: StrictBool
    track_created: StrictBool
    placed: StrictBool


class MusicObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    media_path: StrictStr = Field(min_length=1)
    imported: StrictBool
    placed_on_timeline: StrictBool


class DuplicateObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    sequence: StrictInt = Field(ge=0)
    render_reference: StrictInt = Field(ge=0)
    captions: StrictInt = Field(ge=0)


class PremiereBridgeReceipt(BaseModel):
    """Strict, hash-bound observations returned by the native Premiere host."""

    model_config = ConfigDict(extra="forbid", strict=True)
    protocol_version: Literal[BRIDGE_PROTOCOL_VERSION]
    operation_id: StrictStr = Field(min_length=1)
    job_id: StrictStr = Field(pattern=r"^[0-9a-f]{12}$")
    artifact_identity: ArtifactIdentity
    premiere_version: StrictStr = Field(min_length=1)
    project: ProjectObservation
    sequence: SequenceObservation
    render_reference: MediaObservation
    captions: CaptionObservation
    music: MusicObservation | None = None
    duplicates: DuplicateObservation
    caption_api_available: StrictBool = False
    warnings: list[StrictStr]
    errors: list[StrictStr]


CEP_CAPTION_WARNING_PREFIX = "CEP cannot inspect existing caption tracks"


def verify_saved_captions(project: Path, srt: Path) -> dict[str, Any]:
    """Count caption tracks/items in the saved .prproj and compare them to the SRT cues."""
    result = {"verified": False, "tracks": 0, "items": 0, "cues": 0}
    try:
        cues = [b for b in re.split(r"\r?\n\s*\r?\n", srt.read_text(encoding="utf-8").strip()) if b.strip()]
        raw = project.read_bytes()
        xml = (gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw).decode("utf-8", "replace")
    except (OSError, EOFError, gzip.BadGzipFile, UnicodeError):
        return result
    result["cues"] = len(cues)
    result["tracks"] = len(re.findall(r"<CaptionDataClipTrack[ >]", xml))
    result["items"] = len(re.findall(r"<CaptionDataClipTrackItem[ >]", xml))
    result["verified"] = result["tracks"] == 1 and result["cues"] > 0 and result["items"] == result["cues"]
    return result


def _classify_receipt(observed: PremiereBridgeReceipt,
                      saved_captions: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
    persisted = bool(saved_captions and saved_captions["verified"] and observed.project.saved)
    warnings = ([w for w in observed.warnings if not w.startswith(CEP_CAPTION_WARNING_PREFIX)]
                if persisted else list(observed.warnings))
    required = {
        "project.opened": observed.project.opened,
        "project.saved": observed.project.saved,
        "sequence.imported": observed.sequence.imported,
        "sequence.timeline_open": observed.sequence.timeline_open,
        "render_reference.imported": observed.render_reference.imported,
        "captions.imported": observed.captions.imported,
        "captions.track_created": observed.captions.track_created or persisted,
        "captions.placed": observed.captions.placed or persisted,
    }
    false_required = [name for name, value in required.items() if value is not True]
    music_missing = bool(observed.music and
                         (not observed.music.imported or not observed.music.placed_on_timeline))
    duplicate_counts = observed.duplicates.model_dump()
    invariant_failure = observed.render_reference.placed_on_editable_timeline is not False
    has_duplicates = any(value != 0 for value in duplicate_counts.values())
    if observed.errors or invariant_failure:
        state = "failed"
    elif false_required and not warnings:
        state = "failed"
    elif warnings or false_required or has_duplicates or music_missing:
        state = "partial"
    else:
        state = "completed"
    return state, {
        "caption_persistence": saved_captions,
        "false_required_observations": false_required,
        "render_reference_timeline_violation": invariant_failure,
        "duplicate_counts": duplicate_counts,
        "music_missing": music_missing,
    }


@dataclass
class BridgeSession:
    operation_id: str
    job_id: str
    pairing_code: str
    token_hash: str
    command: dict[str, Any]
    created_at: float = field(default_factory=time.time)
    state: str = "waiting_for_premiere"
    bridge: dict[str, Any] | None = None

    @property
    def expires_at(self) -> float:
        return self.created_at + SESSION_TTL_SECONDS


_sessions: dict[str, BridgeSession] = {}
_pairing_codes: dict[str, str] = {}
_guard = threading.Lock()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _purge_expired(now: float | None = None) -> None:
    current = time.time() if now is None else now
    expired = [operation_id for operation_id, item in _sessions.items()
               if item.expires_at <= current]
    for operation_id in expired:
        item = _sessions.pop(operation_id)
        _pairing_codes.pop(item.pairing_code, None)


def _receipt_path(job) -> Path:
    return job.dir / RECEIPT_FILE


def _read_receipt(job) -> dict[str, Any] | None:
    path = _receipt_path(job)
    if not path.is_file() or path.is_symlink():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("job_id") != job.id or payload.get("protocol_version") != BRIDGE_PROTOCOL_VERSION:
            return None
        native_fields = set(PremiereBridgeReceipt.model_fields)
        observed = PremiereBridgeReceipt.model_validate(
            {key: value for key, value in payload.items() if key in native_fields})
        saved = (payload.get("verification") or {}).get("caption_persistence")
        project = job.dir / Path(payload["artifact_identity"]["project_path"]).name
        if (project.is_file() and not project.is_symlink() and
                premiere_desktop.sha256(project) == payload.get("project_sha256")):
            saved = verify_saved_captions(project, job.dir / PREMIERE_CAPTIONS)
        state, verification = _classify_receipt(observed, saved)
        if payload.get("state") != state or payload.get("verification") != verification:
            return None
        return payload
    except (OSError, ValueError, json.JSONDecodeError, ValidationError):
        return None


def _write_receipt(job, payload: dict[str, Any]) -> None:
    path = _receipt_path(job)
    tmp = job.dir / f".{RECEIPT_FILE}.{secrets.token_hex(4)}.tmp"
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(path)


def _current_receipt(job, identity: dict[str, Any], project: Path) -> dict[str, Any] | None:
    receipt = _read_receipt(job)
    if not receipt:
        return None
    expected = {
        "plan_sha256": identity["plan_sha256"],
        "xml_sha256": identity["xml_sha256"],
        "srt_sha256": identity["srt_sha256"],
        "project_path": str(project),
    }
    if any(receipt.get("artifact_identity", {}).get(key) != value for key, value in expected.items()):
        return None
    render = premiere_desktop.current_render(job, identity["plan_sha256"])[0]
    render_hash = premiere_desktop.sha256(render) if render else None
    if receipt.get("artifact_identity", {}).get("render_sha256") != render_hash:
        return None
    recorded_project_hash = receipt.get("project_sha256")
    if recorded_project_hash and recorded_project_hash != premiere_desktop.sha256(project):
        return None
    return receipt


def _linked_project(job) -> Path:
    record = premiere_desktop.read_link(job)
    if not record:
        raise HTTPException(409, "Link the clean AI Render Premiere project before connecting the bridge")
    status = premiere_desktop.status(job)
    if status.get("project_state") != "linked_current":
        raise HTTPException(409, "The linked Premiere project is outdated; refresh and relink it first")
    return premiere_desktop.safe_file(job, Path(record["project_path"]))


def create_session(job, *, force_refresh: bool = False) -> dict[str, Any]:
    identity = premiere_desktop.current_identity(job, regenerate=True)
    render, render_kind = premiere_desktop.current_render(job, identity["plan_sha256"])
    if not render or render_kind not in ("final", "preview_only"):
        raise HTTPException(409, "A current render is required before connecting to Premiere")
    if force_refresh and premiere_desktop.status(job).get('project_state') != 'linked_current':
        raise HTTPException(409, 'Update and save the linked Premiere project, then link it again before reconnecting')
    project = _linked_project(job)
    previous = _current_receipt(job, identity, project)
    operation_id = secrets.token_urlsafe(18)
    token = secrets.token_urlsafe(32)
    pairing_code = "-".join(secrets.token_hex(2).upper() for _ in range(3))
    artifact_identity = {
        "plan_sha256": identity["plan_sha256"],
        "xml_sha256": identity["xml_sha256"],
        "srt_sha256": identity["srt_sha256"],
        "render_sha256": premiere_desktop.sha256(render),
        "project_path": str(project),
    }
    previous_sequence = (previous or {}).get("sequence", {})
    previous_render = (previous or {}).get("render_reference", {})
    previous_captions = (previous or {}).get("captions", {})
    command = {
        "protocol_version": BRIDGE_PROTOCOL_VERSION,
        "operation_id": operation_id,
        "job_id": job.id,
        "artifact_identity": artifact_identity,
        "expected_project_path": str(project),
        "sequence_name": "AI Render editable sequence",
        "bin_name": "AI Render",
        "render_reference_name": "AI Render — Rendered Reference",
        "files": {
            "xml": str(premiere_desktop.safe_file(job, job.dir / PREMIERE_XML)),
            "render": str(render),
            "captions": str(premiere_desktop.safe_file(job, job.dir / PREMIERE_CAPTIONS)),
        },
    }
    # Add music file to command if plan has music
    plan_data = jobstore.load_plan(job)
    if plan_data.get("music") and plan_data["music"].get("file"):
        music_path = Path(plan_data["music"]["file"])
        if not music_path.is_absolute():
            music_path = job.dir / music_path
        if music_path.is_file():
            command["files"]["music"] = str(music_path)
    command["requested_actions"] = {
        "activate_project": True,
        "import_sequence": not bool(previous_sequence.get("imported")),
        "open_timeline": True,
        "import_render_reference": not bool(previous_render.get("imported")),
        "place_captions": not bool(
            previous_captions.get("track_created") and previous_captions.get("placed")
        ),
        "save_project": True,
    }
    session = BridgeSession(operation_id, job.id, pairing_code, _token_hash(token), command)
    # The raw token is returned only after proof of the one-time pairing code.
    session.command["_issued_token"] = token
    with _guard:
        _purge_expired()
        for old_id, old in list(_sessions.items()):
            if old.job_id == job.id and old.state not in {"completed", "partial", "failed"}:
                _pairing_codes.pop(old.pairing_code, None)
                _sessions.pop(old_id, None)
        _sessions[operation_id] = session
        _pairing_codes[pairing_code] = operation_id
    return {
        "operation_id": operation_id,
        "pairing_code": pairing_code,
        "state": session.state,
        "expires_in_seconds": SESSION_TTL_SECONDS,
        "bridge_kind": "CEP",
        "supported_premiere": "25.0-25.5",
    }


def pending() -> dict[str, Any]:
    """Return the oldest waiting_for_premiere session (loopback-only callers)."""
    with _guard:
        _purge_expired()
        for session in _sessions.values():
            if session.state == "waiting_for_premiere":
                return {
                    "pending": True,
                    "pairing_code": session.pairing_code,
                    "job_id": session.job_id,
                    "sequence_name": session.command.get("sequence_name", ""),
                    "expires_in_seconds": max(0, int(session.expires_at - time.time())),
                }
    return {"pending": False}


def pair(pairing_code: str, bridge: dict[str, Any]) -> dict[str, Any]:
    normalized = pairing_code.strip().upper()
    with _guard:
        _purge_expired()
        operation_id = _pairing_codes.pop(normalized, None)
        session = _sessions.get(operation_id or "")
        if not session:
            raise HTTPException(401, "Pairing code is invalid or has expired — request a new one from AI Render")
        if session.state != "waiting_for_premiere":
            raise HTTPException(401, f"This pairing code cannot be used (current state: {session.state}). Request a new code from AI Render")
        session.state = "paired"
        session.bridge = bridge
        token = session.command.pop("_issued_token")
        command = dict(session.command)
    return {"token": token, "command": command}


def _authenticated(authorization: str | None, operation_id: str) -> BridgeSession:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Bridge bearer token is required")
    token = authorization[7:]
    with _guard:
        _purge_expired()
        session = _sessions.get(operation_id)
        if not session or not secrets.compare_digest(session.token_hash, _token_hash(token)):
            raise HTTPException(401, "Bridge token is invalid or expired")
        return session


def accept_receipt(job, operation_id: str, authorization: str | None,
                   receipt: dict[str, Any] | PremiereBridgeReceipt) -> dict[str, Any]:
    session = _authenticated(authorization, operation_id)
    if session.state in {"completed", "partial", "failed"}:
        raise HTTPException(409, "This bridge operation already has a final receipt")
    if session.job_id != job.id:
        raise HTTPException(403, "Bridge token is scoped to a different job")
    try:
        observed = (receipt if isinstance(receipt, PremiereBridgeReceipt)
                    else PremiereBridgeReceipt.model_validate(receipt))
    except ValidationError as exc:
        raise HTTPException(422, {"message": "Premiere receipt is malformed", "errors": exc.errors()})
    receipt_data = observed.model_dump()
    if observed.operation_id != operation_id or observed.job_id != job.id:
        raise HTTPException(422, "Receipt identity does not match the bridge operation")
    if receipt_data["artifact_identity"] != session.command["artifact_identity"]:
        raise HTTPException(409, "Receipt artifact identity does not match the requested command")
    expected_project = session.command["expected_project_path"]
    if (observed.project.requested_path != expected_project or
            observed.project.active_path != expected_project):
        raise HTTPException(409, "Receipt project path does not match the requested project")
    if observed.sequence.name != session.command["sequence_name"]:
        raise HTTPException(409, "Receipt sequence identity does not match the requested sequence")
    if observed.render_reference.media_path != session.command["files"]["render"]:
        raise HTTPException(409, "Receipt render path does not match the requested artifact")
    if observed.captions.media_path != session.command["files"]["captions"]:
        raise HTTPException(409, "Receipt caption path does not match the requested artifact")
    expected_music = session.command["files"].get("music")
    if (observed.music.media_path if observed.music else None) != expected_music:
        raise HTTPException(409, "Receipt music path does not match the requested artifact")
    project = _linked_project(job)
    payload = receipt_data
    payload.update({
        "protocol_version": BRIDGE_PROTOCOL_VERSION,
        "project_sha256": premiere_desktop.sha256(project),
        "received_at_unix": int(time.time()),
        "bridge": session.bridge or {},
    })
    state, verification = _classify_receipt(
        observed, verify_saved_captions(project, job.dir / PREMIERE_CAPTIONS))
    payload["verification"] = verification
    payload["state"] = state
    payload["caption_api_available"] = observed.caption_api_available
    _write_receipt(job, payload)
    with _guard:
        session.state = state
    return {"accepted": True, "state": state}


def status(job) -> dict[str, Any]:
    receipt = _read_receipt(job)
    receipt_current = False
    if receipt:
        try:
            identity = premiere_desktop.current_identity(job, regenerate=False)
            project = _linked_project(job)
            receipt_current = _current_receipt(job, identity, project) is not None
        except (HTTPException, OSError, ValueError):
            receipt_current = False
    active: BridgeSession | None = None
    with _guard:
        _purge_expired()
        candidates = [item for item in _sessions.values() if item.job_id == job.id]
        if candidates:
            active = max(candidates, key=lambda item: item.created_at)
    result: dict[str, Any] = {
        "available": True,
        "protocol_version": BRIDGE_PROTOCOL_VERSION,
        "state": "stale" if receipt and not receipt_current else "not_connected",
        "receipt": receipt,
    }
    if active and active.state not in {"completed", "partial", "failed"}:
        result.update({
            "operation_id": active.operation_id,
            "state": active.state,
            "expires_at_unix": int(active.expires_at),
            "bridge": active.bridge,
        })
    elif receipt and receipt_current:
        result["state"] = receipt.get("state", "completed")
    return result


def require_loopback_peer(request: Request) -> None:
    peer = request.client.host if request.client else ""
    if peer not in premiere_desktop.LOCAL_HOSTS:
        raise HTTPException(403, "Premiere bridge requests are accepted from this machine only")
