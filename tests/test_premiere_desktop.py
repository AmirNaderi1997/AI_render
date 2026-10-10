from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException, Request

from app import jobs, premiere_desktop as desktop
from app.routers.premiere import PremiereOpenBody
from pydantic import ValidationError
from engine.premiere import build_premiere
from engine.schema import validate_plan


@pytest.fixture
def job(tmp_path, media_dir):
    directory = tmp_path / 'abc123def456'
    directory.mkdir()
    (directory / 'raw.mp4').write_bytes((media_dir / 'raw.mp4').read_bytes())
    data = json.loads((Path(__file__).parents[1] / 'samples/plans/cut.json').read_text())
    data['source'] = 'raw.mp4'
    data['captions'] = [{'start': 0, 'end': 1, 'text': 'سلام', 'style': 'normal'}]
    (directory / 'plan.json').write_text(json.dumps(data))
    plan, errors = validate_plan(data, base_dir=directory, check_media=True)
    assert not errors
    build_premiere(plan, directory, base_dir=directory)
    (directory / 'exports').mkdir()
    render = directory / 'exports/v1.mp4'
    render.write_bytes(b'current final render')
    result = jobs.Job(id=directory.name, dir=directory)
    result.render = jobs.RenderState(status='done', output='v1.mp4',
                                     plan_sha256=desktop.sha256(directory / 'plan.json'))
    return result


def _link_clean(job):
    name = f'ai-render-{job.id}-clean.prproj'
    (job.dir / name).write_bytes(b'saved by Premiere')
    return name


def test_combined_action_without_link_starts_manual_first_time_setup(job, monkeypatch):
    calls = []
    monkeypatch.setattr(desktop, 'capability', lambda: {'available': True, 'version': '25.3.0',
        'bundle_id': 'com.adobe.PremierePro.25', 'app_path': '/Applications/Premiere.app',
        'local_launch_supported': True})
    monkeypatch.setattr(desktop, '_run', lambda *args: calls.append(args))
    assert desktop.status(job)['final_render'] == 'final'
    response = desktop.open_mode(job, 'plan_and_render')
    assert response['status'] == 'setup_required'
    assert response['files'] == ['project_premiere.xml', 'v1.mp4', 'premiere_captions.srt']
    assert calls == [('-b', 'com.adobe.PremierePro.25'), ('-R', str(job.dir))]
    assert 'manual' in response['message'] and f'ai-render-{job.id}-clean.prproj' in response['message']


def test_combined_action_opens_exact_current_link_without_imports(job, monkeypatch):
    name = _link_clean(job)
    desktop.link_project(job, name)
    calls = []
    monkeypatch.setattr(desktop, 'capability', lambda: {'available': True, 'version': '25.3.0',
        'bundle_id': 'com.adobe.PremierePro.25', 'app_path': '/Applications/Premiere.app',
        'local_launch_supported': True})
    monkeypatch.setattr(desktop, '_run', lambda *args: calls.append(args))
    response = desktop.open_mode(job, 'plan_and_render')
    assert response['status'] == 'launch_requested'
    assert calls == [('-b', 'com.adobe.PremierePro.25', str(job.dir / name))]
    assert 'Confirm the editable sequence' in response['message']


def test_combined_action_outdated_link_reveals_only_and_reports_changed_hashes(job, monkeypatch):
    name = _link_clean(job)
    desktop.link_project(job, name)
    (job.dir / 'exports/v1.mp4').write_bytes(b'changed final render')
    calls = []
    monkeypatch.setattr(desktop, 'capability', lambda: {'available': True, 'version': '25.3.0',
        'bundle_id': 'com.adobe.PremierePro.25', 'app_path': '/Applications/Premiere.app',
        'local_launch_supported': True})
    monkeypatch.setattr(desktop, '_run', lambda *args: calls.append(args))
    assert desktop.status(job)['project_state'] == 'linked_outdated'
    response = desktop.open_mode(job, 'plan_and_render')
    assert response['status'] == 'refresh_required'
    assert 'render_sha256' in response['changed_hashes']
    assert calls == [('-R', str(job.dir))]


def test_unrelated_link_target_is_never_opened(job, monkeypatch):
    outsider = job.dir.parent / 'unrelated.prproj'
    outsider.write_bytes(b'unrelated')
    (job.dir / desktop.LINK_FILE).write_text(json.dumps({
        'job_id': job.id, 'project_path': str(outsider),
        'plan_sha256': desktop.sha256(job.dir / 'plan.json'),
        'xml_sha256': desktop.sha256(job.dir / desktop.PREMIERE_XML),
        'srt_sha256': desktop.sha256(job.dir / desktop.PREMIERE_CAPTIONS),
        'render_sha256': desktop.sha256(job.dir / 'exports/v1.mp4'),
    }))
    calls = []
    monkeypatch.setattr(desktop, 'capability', lambda: {'available': True, 'version': '25.3.0',
        'bundle_id': 'com.adobe.PremierePro.25', 'app_path': '/Applications/Premiere.app',
        'local_launch_supported': True})
    monkeypatch.setattr(desktop, '_run', lambda *args: calls.append(args))
    response = desktop.open_mode(job, 'plan_and_render')
    assert response['status'] == 'setup_required'
    assert all(str(outsider) not in arg for call in calls for arg in call)


def test_repeated_combined_action_is_idempotent_and_keeps_project_path(job, monkeypatch):
    name = _link_clean(job)
    desktop.link_project(job, name)
    calls = []
    monkeypatch.setattr(desktop, 'capability', lambda: {'available': True, 'version': '25.3.0',
        'bundle_id': 'com.adobe.PremierePro.25', 'app_path': '/Applications/Premiere.app',
        'local_launch_supported': True})
    monkeypatch.setattr(desktop, '_run', lambda *args: calls.append(args))
    for _ in range(3):
        desktop.open_mode(job, 'plan_and_render')
    record = json.loads((job.dir / desktop.LINK_FILE).read_text())
    assert record['project_path'] == str((job.dir / name).resolve())
    assert calls == [('-b', 'com.adobe.PremierePro.25', str(job.dir / name))] * 3


def test_xml_and_srt_hash_changes_make_package_stale(job):
    xml = job.dir / desktop.PREMIERE_XML
    xml.write_text(xml.read_text() + '\n')
    with pytest.raises(HTTPException) as error:
        desktop.current_identity(job, regenerate=False)
    assert error.value.status_code == 409


def test_srt_hash_change_makes_package_stale(job):
    captions = job.dir / desktop.PREMIERE_CAPTIONS
    captions.write_text(captions.read_text() + '\n')
    with pytest.raises(HTTPException) as error:
        desktop.current_identity(job, regenerate=False)
    assert error.value.status_code == 409


def test_clean_project_filename_is_required(job):
    _link_clean(job)
    with pytest.raises(HTTPException) as error:
        desktop.link_project(job, f'ai-render-{job.id}.prproj')
    assert error.value.status_code == 422


def test_preview_requires_confirmation_and_old_final_is_not_used(job, monkeypatch):
    monkeypatch.setattr(desktop, 'capability', lambda: {'available': True,
        'bundle_id': 'com.adobe.PremierePro.25', 'local_launch_supported': True})
    calls = []
    monkeypatch.setattr(desktop, '_run', lambda *args: calls.append(args))
    (job.dir / 'exports/v2_preview.mp4').write_bytes(b'preview')
    job.render.output = 'v2_preview.mp4'
    job.render.preview = True
    with pytest.raises(HTTPException) as error:
        desktop.open_mode(job, 'rendered_video')
    assert error.value.status_code == 409 and not calls
    response = desktop.open_mode(job, 'rendered_video', confirm_preview=True)
    assert response['status'] == 'setup_required'
    assert calls == [('-b', 'com.adobe.PremierePro.25'), ('-R', str(job.dir))]
    job.render.plan_sha256 = '0' * 64
    assert desktop.current_render(job, desktop.sha256(job.dir / 'plan.json')) == (None, 'outdated')
    with pytest.raises(HTTPException):
        desktop.open_mode(job, 'rendered_video', confirm_preview=True)
    job.render.output = 'v1.mp4'
    job.render.preview = False
    job.render.plan_sha256 = '0' * 64
    with pytest.raises(HTTPException):
        desktop.open_mode(job, 'rendered_video')


def test_project_link_survives_reload_and_marks_plan_change(job):
    name = _link_clean(job)
    project = job.dir / name
    assert desktop.link_project(job, name)['status'] == 'linked'
    reloaded = jobs.Job(id=job.id, dir=job.dir, render=job.render)
    assert desktop.status(reloaded)['saved_project'] == 'linked'
    plan_file = job.dir / 'plan.json'
    plan_file.write_text(plan_file.read_text() + '\n')
    changed = desktop.status(reloaded)
    assert changed['saved_project'] == 'outdated'
    assert changed['editable_plan'] == 'stale'
    assert changed['final_render'] == 'outdated'


def test_saving_unchanged_plan_keeps_file_bytes_and_render_current(job):
    before = desktop.sha256(job.dir / 'plan.json')
    data = json.loads((job.dir / 'plan.json').read_text())
    _, errors = jobs.save_plan(job, data)
    assert not errors
    assert desktop.sha256(job.dir / 'plan.json') == before
    assert desktop.status(job)['final_render'] == 'final'
    data['captions'][0]['text'] = 'changed'
    jobs.save_plan(job, data)
    assert desktop.sha256(job.dir / 'plan.json') != before


def test_symlink_escape_is_rejected_before_regeneration_or_link(job, tmp_path):
    outside = tmp_path / 'outside.xml'
    outside.write_text('untouched')
    (job.dir / 'project_premiere.xml').unlink()
    (job.dir / 'project_premiere.xml').symlink_to(outside)
    with pytest.raises(HTTPException) as error:
        desktop.current_identity(job, regenerate=True)
    assert error.value.status_code == 422 and outside.read_text() == 'untouched'
    outside_project = tmp_path / 'outside.prproj'
    outside_project.write_bytes(b'project')
    (job.dir / f'ai-render-{job.id}-clean.prproj').symlink_to(outside_project)
    with pytest.raises(HTTPException):
        desktop.link_project(job, f'ai-render-{job.id}-clean.prproj')


def _request(peer: str, host: str, origin: str | None = None) -> Request:
    headers = [(b'host', host.encode())]
    if origin:
        headers.append((b'origin', origin.encode()))
    return Request({'type': 'http', 'method': 'POST', 'scheme': 'http',
                    'server': (host, 8000), 'client': (peer, 1234),
                    'path': '/jobs/x/premiere/open', 'headers': headers})


def test_remote_and_foreign_origin_cannot_launch(monkeypatch):
    monkeypatch.setattr(desktop.sys, 'platform', 'darwin')
    desktop.require_local(_request('127.0.0.1', 'localhost', 'http://localhost:5173'))
    for request in (_request('10.0.0.8', 'localhost'),
                    _request('127.0.0.1', 'example.com'),
                    _request('127.0.0.1', 'localhost', 'https://attacker.example')):
        with pytest.raises(HTTPException) as error:
            desktop.require_local(request)
        assert error.value.status_code == 403


def test_open_request_rejects_arbitrary_browser_path():
    with pytest.raises(ValidationError):
        PremiereOpenBody.model_validate({'mode': 'editable_plan', 'path': '/tmp/other.xml'})


def test_status_reports_missing_premiere_as_200_with_available_false(job, monkeypatch):
    from app.routers import premiere as router

    monkeypatch.setattr(desktop, 'capability', lambda: {'available': False,
        'local_launch_supported': True, 'version': None, 'bundle_id': None, 'app_path': None})
    monkeypatch.setattr(desktop, 'require_local', lambda request: None)
    monkeypatch.setattr(router.premiere_desktop, 'job_for_id', lambda job_id: job)
    monkeypatch.setattr(router, 'verify_job_owner', lambda request, job: None)

    response = router.premiere_desktop_status(job.id, request=None)
    assert response['available'] is False
    assert response['message'] == 'Premiere Pro not detected'
    # The full status payload stays intact so XML/ZIP export and render state still render.
    assert response['capability']['available'] is False
    assert response['final_render'] == 'final'
    assert 'bridge' in response


def test_status_reports_detected_premiere_as_available(job, monkeypatch):
    from app.routers import premiere as router

    monkeypatch.setattr(desktop, 'capability', lambda: {'available': True, 'version': '25.3.0',
        'bundle_id': 'com.adobe.PremierePro.25', 'app_path': '/Applications/Premiere.app',
        'local_launch_supported': True})
    monkeypatch.setattr(desktop, 'require_local', lambda request: None)
    monkeypatch.setattr(router.premiere_desktop, 'job_for_id', lambda job_id: job)
    monkeypatch.setattr(router, 'verify_job_owner', lambda request, job: None)

    response = router.premiere_desktop_status(job.id, request=None)
    assert response['available'] is True
    assert response['message'] is None
