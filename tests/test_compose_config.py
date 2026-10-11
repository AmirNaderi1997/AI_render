from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_api_can_persist_my_effects_while_worker_presets_stay_read_only():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())

    app_volumes = compose["services"]["app"]["volumes"]
    worker_volumes = compose["services"]["celery-worker"]["volumes"]

    assert "./presets:/app/presets" in app_volumes
    assert "./presets:/app/presets:ro" not in app_volumes
    assert "./presets:/app/presets:ro" in worker_volumes
