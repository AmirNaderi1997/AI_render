# Planning, building, and VPS handoff guideline

## Before planning

- Read `SKILLS.md`, `Prompts/README.md`, `RoadMap.md`, the relevant detailed docs, and the current code.
- Inspect `git status` and preserve unrelated edits. Identify the exact outcome, affected layers, contracts, and measurable acceptance criteria.
- Put the scoped plan and any dependencies in `RoadMap.md` or a linked plan. Keep prompts and plans free of secrets.

## During building

- Implement all layers required by the change. For persistent or queued features, include database migration and worker behavior; for user-visible features, include frontend and real browser acceptance; for rendering, inspect actual output media.
- Run focused tests and build/config checks. Record command, result, environment, and any skipped or unverified path. Update `SKILLS.md` and `Prompts/README.md` if capability or task contract changes.

## Before sending to the VPS

1. Confirm `SKILLS.md`, `Prompts/README.md`, `RoadMap.md`, and `GuideLine.md` are present and updated for this release. Run `python3 scripts/check_vps_handoff.py`.
2. Review [PRODUCTION_CHECKLIST.md](PRODUCTION_CHECKLIST.md) and [docs/VPS_PRODUCTION_PLAN.md](docs/VPS_PRODUCTION_PLAN.md). Record the revision, migration and configuration changes, evidence, owner, open gates, and rollback target.
3. On the intended VPS, verify DNS, trusted TLS files, production environment values, storage capacity, and a restorable PostgreSQL backup before migration. Never include secret values in the handoff.
4. Use the reviewed production Compose path and deployment script. Check migration output, container health, readiness, HTTPS, logs, and worker operation. Test affected real browser and media workflows on the final domain.
5. If any gate is incomplete, report the project as pending and name the missing evidence. Do not equate a successful preflight or local build with a production deployment.

`./deploy.sh` and `./scripts/deploy.sh` run the four-file preflight before changing the VPS. The preflight checks presence and nonempty content; the release reviewer must assess correctness and current evidence.
