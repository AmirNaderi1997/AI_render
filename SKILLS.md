# AI Render skills for planning, building, and VPS handoff

This is the entry point for capabilities needed to ship this project. The detailed engine and AI skill catalog is [docs/skills.md](docs/skills.md); the current stage descriptions are [docs/stages.md](docs/stages.md).

| Capability | Main implementation | Acceptance evidence before VPS handoff |
| --- | --- | --- |
| Edit plan and rendering | `engine/`, `brain/planner.py`, `presets/` | Valid plan, real media render, inspectable video/audio and export files |
| Export quality baseline | `engine/technical_qc.py`, `engine/build_mlt.py`, `brain/music.py` | Inspect portrait hook and captions, measure final and music-mixed loudness, review export warnings |
| API and persistence | `app/`, `hermes/`, `alembic/` | Focused API tests, migration review, database-backed workflow |
| User experience | `web/` | Build plus visible browser checks of the changed flow |
| Background processing | `app/celery_app.py`, `app/tasks.py`, Redis | Job transitions, worker health, retry/failure behavior |
| Deployment and operations | Compose files, `nginx/`, `scripts/deploy.sh`, `deploy.sh` | Config/build checks, PostgreSQL backup and migration, readiness, HTTPS, rollback plan |

For each planned change, identify the affected rows, name the owner and acceptance evidence, and record any missing skill or dependency in [RoadMap.md](RoadMap.md) or a linked scoped plan. Use [Prompts/README.md](Prompts/README.md) for a repeatable task handoff and [GuideLine.md](GuideLine.md) for the release workflow.
