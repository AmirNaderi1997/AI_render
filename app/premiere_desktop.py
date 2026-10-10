"""Local macOS handoff for existing Premiere interchange artifacts.

The backend never writes a native .prproj. An OS handoff is not an import receipt.
"""
from __future__ import annotations

import hashlib
import json
import plistlib
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException, Request

from engine.premiere import (PREMIERE_BUNDLE, PREMIERE_CAPTIONS, PREMIERE_REPORT,
                             PREMIERE_XML, _plan_sha256, build_premiere)
from engine.schema import validate_plan
from . import jobs as jobstore

APP_PATHS = (Path('/Applications/Adobe Premiere Pro 2025/Adobe Premiere Pro 2025.app'),
             Path('/Applications/Adobe Premiere Pro 2025.app'))
LINK_FILE = 'premiere_project_link.json'
MODES = {'editable_plan', 'rendered_video', 'plan_and_render', 'saved_project', 'reveal'}
LOCAL_HOSTS = {'localhost', '127.0.0.1', '::1'}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def capability() -> dict:
    result = {'available': False, 'local_launch_supported': sys.platform == 'darwin',
              'version': None, 'bundle_id': None, 'app_path': None}
    if sys.platform != 'darwin':
        return result
    for app_path in APP_PATHS:
        try:
            with (app_path / 'Contents' / 'Info.plist').open('rb') as stream:
                info = plistlib.load(stream)
            bundle = info.get('CFBundleIdentifier')
            version = info.get('CFBundleShortVersionString')
            if app_path.is_dir() and bundle == 'com.adobe.PremierePro.25' and version:
                result.update(available=True, version=version, bundle_id=bundle,
                              app_path=str(app_path))
                break
        except (OSError, ValueError, TypeError):
            continue
    return result


def require_local(request: Request) -> None:
    """Protect desktop side effects from remote deployments and browser CSRF."""
    from urllib.parse import urlsplit
    peer = request.client.host if request.client else ''
    host = request.url.hostname or ''
    origin = request.headers.get('origin')
    if (sys.platform != 'darwin' or peer not in LOCAL_HOSTS or host not in LOCAL_HOSTS or
            (origin and urlsplit(origin).hostname not in LOCAL_HOSTS)):
        raise HTTPException(403, 'Desktop launch is local only. Download the files and import them manually.')


def job_for_id(job_id: str):
    if not re.fullmatch(r'[0-9a-f]{12}', job_id):
        raise HTTPException(404, 'job not found')
    job = jobstore.get(job_id)
    if not job or job.dir.is_symlink() or job.dir.resolve().parent != jobstore.JOBS_ROOT.resolve():
        raise HTTPException(404, 'job not found')
    return job


def safe_file(job, path: Path) -> Path:
    root = job.dir.resolve()
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError):
        raise HTTPException(404, f'File missing: {path.name}')
    if not resolved.is_relative_to(root) or not resolved.is_file() or path.is_symlink():
        raise HTTPException(422, 'File must be a regular file inside this job directory, without a symlink escape')
    return resolved


def current_identity(job, *, regenerate: bool) -> dict:
    try:
        plan_data = jobstore.load_plan(job)
    except FileNotFoundError as exc:
        raise HTTPException(409, "Generate a plan first") from exc
    source = jobstore.source_media_path(job)
    if source is not None and not source.is_file():
        raise HTTPException(404, "Source media missing")
    plan, errors = validate_plan(plan_data, base_dir=job.dir, check_media=True)
    if errors:
        raise HTTPException(422, errors)
    plan_hash = _plan_sha256(plan, job.dir)
    if regenerate:
        for name in (PREMIERE_XML, PREMIERE_CAPTIONS, PREMIERE_REPORT, PREMIERE_BUNDLE):
            if (job.dir / name).is_symlink():
                raise HTTPException(422, 'Premiere artifact path cannot be a symlink')
        try:
            build_premiere(plan, job.dir, base_dir=job.dir, attached_music=jobstore.attached_music(job))
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(422, f'Premiere export could not package its media: {exc}') from exc
    report_file = job.dir / PREMIERE_REPORT
    xml_file = job.dir / PREMIERE_XML
    try:
        report = json.loads(safe_file(job, report_file).read_text(encoding='utf-8'))
        xml_hash = sha256(safe_file(job, xml_file))
        safe_file(job, job.dir / PREMIERE_CAPTIONS)
        safe_file(job, job.dir / PREMIERE_BUNDLE)
    except (ValueError, json.JSONDecodeError):
        raise HTTPException(422, 'Premiere package is invalid; regenerate it before opening')
    identity = report.get('artifact_identity') or {}
    srt_hash = sha256(safe_file(job, job.dir / PREMIERE_CAPTIONS))
    if (identity.get('job_id') != job.id or identity.get('plan_sha256') != plan_hash or
            identity.get('xml_sha256') != xml_hash or identity.get('srt_sha256') != srt_hash):
        raise HTTPException(409, 'Premiere package is stale; regenerate it before opening')
    return {'plan_sha256': plan_hash, 'xml_sha256': xml_hash, 'srt_sha256': srt_hash, 'report': report}


def current_render(job, plan_hash: str) -> tuple[Path | None, str]:
    render = job.render
    if render.status != 'done' or not render.output:
        return None, 'missing'
    if render.plan_sha256 != plan_hash:
        return None, 'outdated'
    if render.preview or '_preview' in render.output:
        if not re.fullmatch(r'v[0-9]+_preview\.mp4', render.output):
            raise HTTPException(422, 'Unexpected preview filename')
        return safe_file(job, job.dir / 'exports' / render.output), 'preview_only'
    if not re.fullmatch(r'v[0-9]+\.mp4', render.output):
        raise HTTPException(422, 'Unexpected render filename')
    return safe_file(job, job.dir / 'exports' / render.output), 'final'


def link_path(job) -> Path:
    return job.dir / LINK_FILE


def read_link(job) -> dict | None:
    path = link_path(job)
    if not path.exists():
        return None
    try:
        record = json.loads(safe_file(job, path).read_text(encoding='utf-8'))
        allowed = {(job.dir / f'ai-render-{job.id}-clean.prproj').resolve()}
        expected = Path(record.get('project_path', '')).resolve()
        if record.get('job_id') != job.id or expected not in allowed:
            return None
        safe_file(job, expected)
        return record
    except (ValueError, json.JSONDecodeError, HTTPException):
        return None


def status(job) -> dict:
    cap = capability()
    result = {'capability': cap, 'editable_plan': 'missing', 'final_render': 'missing',
              'saved_project': 'not_linked', 'project_state': 'not_linked',
              'warnings': [], 'render_name': None, 'artifact_hashes': {},
              'xml_name': PREMIERE_XML, 'srt_name': PREMIERE_CAPTIONS}
    link_present = link_path(job).exists()
    record = read_link(job)
    if link_present and record is None:
        result['project_state'] = 'missing'
        result['saved_project'] = 'outdated'
    try:
        identity = current_identity(job, regenerate=False)
        result['editable_plan'] = 'ready'
        result['warnings'] = identity['report'].get('warnings', [])
    except HTTPException as exc:
        if exc.status_code == 409 and exc.detail == "Generate a plan first":
            raise
        if exc.status_code == 404 and exc.detail == "Source media missing":
            raise
        result['editable_plan'] = 'stale' if exc.status_code == 409 else 'missing'
        result['warnings'] = [str(exc.detail)]
        if (job.render.status == 'done' and job.render.output and not job.render.preview and
                job.plan_data is not None and job.render.plan_sha256 != _plan_sha256(
                    validate_plan(job.plan_data, base_dir=job.dir, check_media=True)[0], job.dir
                )):
            result['final_render'] = 'outdated'
        if record:
            result['saved_project'] = 'outdated'
            result['project_state'] = 'linked_outdated'
            result['warnings'].append('Premiere project may be outdated. The current plan or package needs regeneration.')
        return result
    try:
        render, kind = current_render(job, identity['plan_sha256'])
    except HTTPException:
        render, kind = None, 'missing'
    result['final_render'] = kind
    result['render_name'] = render.name if render else None
    result['artifact_hashes'] = {'plan': identity['plan_sha256'], 'xml': identity['xml_sha256'],
                                 'srt': identity['srt_sha256'],
                                 'render': sha256(render) if render and kind == 'final' else None}
    if record:
        result['saved_project'] = 'linked'
        current = {k: identity[k] for k in ('plan_sha256', 'xml_sha256')}
        current['srt_sha256'] = identity['srt_sha256']
        current['render_sha256'] = sha256(render) if kind == 'final' and render else None
        result['changed_hashes'] = {key: {'linked': record.get(key), 'current': value}
                                    for key, value in current.items()
                                    if record.get(key) != value}
        if any(record.get(k) != value for k, value in current.items()):
            result['saved_project'] = 'outdated'
            result['project_state'] = 'linked_outdated'
            result['warnings'].append('Premiere project may be outdated. Later AI Render edits are not in the saved project automatically.')
        else:
            result['project_state'] = 'linked_current'
        result['project_name'] = Path(record['project_path']).name
    else:
        if not link_present:
            result['project_state'] = 'not_linked'
    result['file_state'] = 'ready'
    if not record:
        expected_clean = job.dir / f'ai-render-{job.id}-clean.prproj'
        if expected_clean.is_file() and not expected_clean.is_symlink():
            result['auto_linkable'] = True
            result['auto_linkable_project'] = expected_clean.name
    return result


def _run(*args: str) -> None:
    try:
        subprocess.run(['/usr/bin/open', *args], check=True, timeout=20)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(502, f'macOS could not hand the file to Premiere/Finder: {exc}')


def open_mode(job, mode: str, *, confirm_preview: bool = False) -> dict:
    if mode not in MODES:
        raise HTTPException(422, 'Unsupported Premiere action')
    identity = current_identity(job, regenerate=True)
    xml = safe_file(job, job.dir / PREMIERE_XML)
    try:
        render, kind = current_render(job, identity['plan_sha256'])
    except HTTPException:
        if mode in {'rendered_video', 'plan_and_render'}:
            raise
        render, kind = None, 'missing'
    cap = capability()
    record = read_link(job)
    state = status(job)
    if mode == 'saved_project':
        if not record:
            raise HTTPException(404, 'No saved Premiere project linked to this job')
        target = safe_file(job, Path(record['project_path']))
    elif mode in {'rendered_video', 'plan_and_render'}:
        if kind == 'preview_only' and not confirm_preview:
            raise HTTPException(409, 'Only a preview is current. Confirm preview use explicitly or make a final render.')
        if not render or kind not in {'final', 'preview_only'}:
            raise HTTPException(409, 'Current final render is missing or outdated. Render this plan before opening.')
        target = render
    else:
        target = xml
    if mode == 'reveal':
        _run('-R', str(job.dir))
        return {'status': 'revealed', 'message': 'Updated Premiere files are visible in Finder.'}
    if not cap['available']:
        raise HTTPException(409, 'Premiere Pro is unavailable. Download and import manually.')
    if mode in {'editable_plan', 'rendered_video'}:
        if record and state['project_state'] == 'linked_current':
            linked = safe_file(job, Path(record['project_path']))
            _run('-b', cap['bundle_id'], str(linked))
            message = 'Opened the linked Premiere project. Confirm the editable sequence, rendered reference, and captions in Premiere.'
            if mode == 'rendered_video':
                message = (f'Opened the linked Premiere project, which holds {render.name} as AI Render — Rendered Reference. '
                           'The MP4 was not opened as a separate item; find it in the AI Render bin.')
            return {'status': 'launch_requested', 'mode': mode, 'target': linked.name,
                    'render_kind': kind, 'message': message}
        _run('-b', cap['bundle_id'])
        _run('-R', str(job.dir))
        render_label = render.name if render else 'the final MP4'
        return {'status': 'setup_required', 'mode': mode,
                'steps': [
                    'Create a new, empty Premiere Pro project.',
                    f'File → Import → select {PREMIERE_XML}.',
                    f'File → Import → select {render_label}; rename the bin item to "AI Render — Rendered Reference".',
                    f'File → Import → select {PREMIERE_CAPTIONS}; place the SRT on the imported sequence as a caption track.',
                    f'File → Save As → save as ai-render-{job.id}-clean.prproj inside the job folder.',
                    'Return to AI Render and click "Link clean Premiere project".',
                ],
                'message': f'Premiere is open and the job files are visible in Finder. Create a dedicated project, import {PREMIERE_XML}, import {render_label}, and import {PREMIERE_CAPTIONS}. Save as ai-render-{job.id}-clean.prproj and link it after Premiere has created that exact file.'}
    if mode == 'plan_and_render':
        if state['project_state'] == 'linked_current':
            _run('-b', cap['bundle_id'], str(safe_file(job, Path(record['project_path']))))
            message = 'Opened the linked Premiere project. Confirm the editable sequence, rendered reference, and captions in Premiere.'
        elif state['project_state'] == 'linked_outdated':
            _run('-R', str(job.dir))
            return {'status': 'refresh_required', 'mode': mode, 'project_state': 'linked_outdated',
                    'hashes': state.get('artifact_hashes', {}),
                    'changed_hashes': state.get('changed_hashes', {}),
                    'xml_name': PREMIERE_XML, 'render_name': render.name if render else None,
                    'srt_name': PREMIERE_CAPTIONS,
                    'message': 'The linked Premiere project is outdated. Updated files are revealed in Finder; replace or import them explicitly, save in Premiere, then relink. AI Render has not updated the project.'}
        else:
            _run('-b', cap['bundle_id'])
            _run('-R', str(job.dir))
            return {'status': 'setup_required', 'mode': mode, 'project_state': 'not_linked',
                    'files': [PREMIERE_XML, render.name, PREMIERE_CAPTIONS],
                    'message': f'Premiere is open and the job files are visible in Finder. Create a clean project dedicated to this job. Import {PREMIERE_XML}, import {render.name} as AI Render — Rendered Reference, import {PREMIERE_CAPTIONS}, place the SRT on the imported sequence as a caption track, then save as ai-render-{job.id}-clean.prproj. These Premiere steps are manual; link only after that exact file exists.'}
    else:
        _run('-b', cap['bundle_id'], str(target))
        if mode != 'saved_project':
            _run('-R', str(target))
            message = 'Sent to Premiere Pro. Confirm that the sequence or media appears in Premiere. The file is selected in Finder for File → Import if needed.'
        else:
            message = 'Sent the saved .prproj to Premiere Pro. Confirm that the project opens and contains your expected sequence and media.'
    return {'status': 'launch_requested', 'mode': mode, 'target': target.name,
            'render_kind': kind, 'message': message}


def link_project(job, project_name: str | None = None) -> dict:
    identity = current_identity(job, regenerate=True)
    expected_name = f'ai-render-{job.id}-clean.prproj'
    if project_name != expected_name:
        raise HTTPException(422, f'Only the clean job project may be linked: {expected_name}')
    project_path = job.dir / expected_name
    if not project_path.exists():
        cap = capability()
        xml = job.dir / PREMIERE_XML
        if cap['available'] and xml.exists():
            _run('-b', cap['bundle_id'])
            _run('-R', str(job.dir))
            return {
                'status': 'setup_started',
                'project_name': expected_name,
                'message': (
                    f'Premiere is open and {PREMIERE_XML} is visible in Finder. Use File → Import in Premiere. '
                    f'Import the rendered MP4 and captions SRT, then File → Save As → '
                    f'"{expected_name}" inside the job folder. Click this button again to link.'
                ),
            }
        raise HTTPException(
            404,
            f'Save a Premiere project as "{expected_name}" inside {job.dir} first, then link it here.'
        )
    project = safe_file(job, project_path)
    existing = read_link(job)
    if existing and status(job)['project_state'] == 'linked_outdated':
        previous_hash = existing.get('project_sha256')
        linked_at = existing.get('linked_at')
        saved_after_link = False
        if isinstance(linked_at, str):
            try:
                saved_after_link = project.stat().st_mtime > datetime.fromisoformat(linked_at).timestamp()
            except ValueError:
                pass
        if (previous_hash == sha256(project) if previous_hash else not saved_after_link):
            raise HTTPException(409, 'The linked project has not been saved since the AI Render artifacts changed. Import the updated files in Premiere, save the project, then link it again.')
    try:
        render, kind = current_render(job, identity['plan_sha256'])
    except HTTPException:
        render, kind = None, 'missing'
    record = {'job_id': job.id, 'project_path': str(project),
              'linked_at': datetime.now(timezone.utc).isoformat(),
              'project_sha256': sha256(project),
              'plan_sha256': identity['plan_sha256'], 'xml_sha256': identity['xml_sha256'],
              'srt_sha256': identity['srt_sha256'],
              'render_sha256': sha256(render) if render and kind == 'final' else None,
              'premiere_version': capability()['version']}
    path = link_path(job)
    pending = path.with_suffix('.tmp')
    if path.is_symlink() or pending.is_symlink():
        raise HTTPException(422, 'Project link metadata path cannot be a symlink')
    pending.write_text(json.dumps(record, indent=2), encoding='utf-8')
    pending.replace(path)
    return {'status': 'linked', 'project_name': project.name, 'linked_at': record['linked_at']}
