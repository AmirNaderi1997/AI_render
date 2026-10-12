# Project work prompts

Use this template when asking an agent or developer to plan, build, or prepare a release. Fill in the fields for the specific task; do not paste credentials or customer media into a prompt.

```text
Goal and user-visible result:
Current behavior and evidence:
Scope and affected layers (backend, frontend, database, worker, Docker, media):
Relevant skill(s) from SKILLS.md:
RoadMap.md item or linked scoped plan:
Constraints and contracts to preserve:
Acceptance checks and expected outputs:
Reference-video traits to match, with measured audio/video values and a fresh visual inspection:
VPS impact (migration, config, storage, TLS, backup, rollback):
```

Before starting, read `SKILLS.md`, `RoadMap.md`, and `GuideLine.md`; inspect the current code and working tree. After building, report the commands and results, what was actually inspected in the browser or media output, and what remains unverified. For a VPS handoff, use the release evidence and gates in `GuideLine.md` and [PRODUCTION_CHECKLIST.md](../PRODUCTION_CHECKLIST.md).

Existing task prompts are under [docs/prompts](../docs/prompts) and [docs/prompt-stage1.md](../docs/prompt-stage1.md). They are historical inputs, not evidence that a feature or deployment is complete.
