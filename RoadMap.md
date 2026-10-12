# AI Render roadmap and VPS release gates

The feature history is in [docs/stages.md](docs/stages.md) and [plan.md](plan.md). The infrastructure outline is [docs/VPS_PRODUCTION_PLAN.md](docs/VPS_PRODUCTION_PLAN.md). Reconcile those plans with the current code and [PRODUCTION_CHECKLIST.md](PRODUCTION_CHECKLIST.md) before treating any stage as complete.

## Planning and building sequence

1. State the user outcome, affected layers, dependencies, and acceptance evidence. Use the template in [Prompts/README.md](Prompts/README.md).
2. Build the smallest complete cross-layer change. Update the relevant API, UI, storage, worker, and Compose pieces when the feature needs them.
3. Verify with focused tests, build/config checks, and a real browser or media workflow for user-visible behavior. Record exact results and limitations in the scoped plan or task report.
4. Update the release evidence and unresolved items in [PRODUCTION_CHECKLIST.md](PRODUCTION_CHECKLIST.md). Only then prepare a VPS handoff under [GuideLine.md](GuideLine.md).

## VPS gate status

| Gate | Required evidence | Current status |
| --- | --- | --- |
| Release scope | Named revision, changed components, migrations, owner, rollback target | Needs review for each release |
| Configuration and TLS | VPS `.env`, DNS, trusted certificate, exact hosts, no secrets in Git | Not proven on VPS in this repository |
| Data safety | Restorable PostgreSQL backup, migration review, storage durability | Not proven on VPS in this repository |
| Runtime | Compose services, DB/Redis/worker readiness, HTTPS, logs | Not proven on VPS in this repository |
| User acceptance | Real login, upload, render, export, Hermes flow as applicable in browser | Not proven on VPS in this repository |
| Hermes credential entry | Users enter their Instagram credentials in the Hermes section of the site; remove the existing environment fallback before treating that policy as enforced | Pending; current code still accepts environment values |

Do not infer deployment readiness from the presence of these documents or from a local build. Update this table only with dated, specific evidence.
