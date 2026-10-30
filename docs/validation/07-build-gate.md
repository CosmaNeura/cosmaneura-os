# 07 — Build gate

Date: 2026-09-02  
Phase: 0 complete — waiting for owner

## Verdict

**`FEASIBLE_WITH_CONDITIONS`**

Fatal findings: **none found**.

Conditions: Postgres-authoritative ledger; L0 fake adapters only; Python **3.13** baseline; minimal React owner queue; no Track A mutation; no PHI/credentials; cloud deploy not authorized by this gate.

## Working assumptions (apply unless owner overrides before build)

1. First slice uses **individual** payload-bound approve/edit/reject/escalate (not batch).
2. Worker = **Celery + Redis** transport; operation rows in Postgres.
3. **Local filesystem BlobPort** (not Azurite) for synth.
4. **No Mailpit required** if NotifyPort is fully fake; optional later.
5. Baseline agents Scribe/Chief/Chaser installed; Chaser performs detection/draft only.
6. Neutral patient message body; fake delivery only.
7. Retention: insurance working copies purge at chase-complete + 7 days via injectable clock.
8. UI hides `box_id`, operation IDs, and compliance jargon.
9. Local `git init` on `main` after approval; **no remote/push**.
10. GPT-5.6 SOL is development-only; no application LLM in product runtime.

## Genuine blocking owner decisions for this slice

**None.** Conservative defaults above are sufficient to build local synth.

Non-blocking opens (do not wait): SaaS tiers, beta clinic identity, batch UX, A2P vs email, Athena/Acuity access, physical packing, product LLM.

If the owner prefers Python **3.12** or a non-React queue (e.g. server-rendered), say so in the approval message; otherwise 3.13 + minimal React proceed.

## Exact proposed first slice

Deterministic local synthetic **Insurance ArtifactChase L0**:

1. Seed one invented Org Box.
2. Seed one owner/approver + Scribe, Chief, Chaser installations.
3. Import invented appointments via SchedulePort L0.
4. Attest invented PatientLink.
5. Detect missing/stale insurance artifact.
6. Create F-8 ticket + neutral message ActionRevision.
7. Show one usable owner queue.
8. Support approve, edit, reject, escalate.
9. Bind approval to target, action, content revision, payload hash.
10. Create/execute one Operation via fake NotifyPort.
11. Prove double-click and worker retry do not duplicate effect.
12. Simulate front/back upload with invented image fixtures + secure-token simulation.
13. Human verification → `IMAGE_ON_FILE`.
14. Close ticket; display audit timeline.
15. Retention/purge via injectable clock; non-PHI receipt retained.

Out of slice: real messaging, Athena, Acuity, Clerk, Azure, application LLM, Capacitor, Teams, payment/PAN, Track A code changes.

## Commands to run after `APPROVE LOCAL SYNTH BUILD`

Illustrative sequence (exact names finalized in README during build):

```bash
cd ~/Desktop/cosmaneura-os
git status   # confirm handoff tree
git init -b main
# scaffold package layout, pyproject, compose, web app
uv sync
docker compose up -d
uv run alembic upgrade head
uv run python -m cosmas_os.cli seed-synth
uv run pytest
# web
cd web && pnpm install && pnpm test && pnpm build
# quality gates
uv run ruff check .
uv run pyright
# demo
uv run python -m cosmas_os.cli demo-artifact-chase
docker compose down
```

No Terraform apply; no Azure login; no Clerk/Stripe/Athena/Acuity calls; no legacy repo edits.

## Files / components to create

- `README.md` (replace bootstrap with runbook), `BUILD_REPORT.md`, `.env.example`
- `pyproject.toml`, `src/cosmas_os/**` (domain, application, ports, adapters, api, worker)
- `migrations/`, `fixtures/synthetic/`, `tests/**`
- `docker-compose.yml`, `infra/local/` notes only
- `web/` minimal queue
- `docs/` capability matrix, threat/recovery, retention, demo walkthrough (as required by mandate)
- Append any owner overrides to `docs/DECISION_LOG.md` before coding

## Definition of done

- One-command local start documented and verified
- Migrations apply on empty Postgres
- Seed + demo walkthrough complete ArtifactChase L0
- Required invariant tests pass (F-8, principals, ledger, PatientLink, dark caps, purge, fixture scan, E2E)
- OpenAPI artifact generated
- No PHI/production credentials in repo
- `BUILD_REPORT.md` lists commands run and exact results
- Sibling legacy `git status --short` unchanged from Phase 0 baselines
- Stop before cloud

## Repository initialization proposal

| Action | When | Allowed? |
|---|---|---|
| `git init -b main` | Immediately after approval, before scaffold | Yes, if this gate accepted |
| Initial commit(s) | When owner requests commits | Only on explicit ask |
| Create GitHub remote / push | Later direct instruction | **No** under this approval |
| Multi-root with `Cosmas/` | Not proposed | Avoid write-boundary risk |

Current state: `~/Desktop/cosmaneura-os` is **not** a git repository.

## Legacy repository before/after status evidence

Captured during Phase 0 inspection; after = before (no mutations).

| Path | Branch | Commit | Dirty lines before | Dirty lines after |
|---|---|---|---|---|
| `~/Desktop/Cosmas/cosmaneura-master` | `legal/baa-v2-3-remove-claims-submission-20260829` | `7d8000a` | 0 | 0 |
| `~/Desktop/Cosmas/cosmaneura-scribe` | `codex/scribe-stt-mobile-roadmap` | `ad5a579` | 45 | 45 |
| `~/Desktop/Cosmas/Cosmas-CAB-Tool-main` | `codex/cab-suggested-codes-card-chase-20260829` | `e3c335d` | 0 | 0 |
| `~/Desktop/Cosmas/cosmaneura-scheduling` | `codex/deployment-readiness-tranche` | `1e63328` | 0 | 0 |
| `~/Desktop/Cosmas/cosmaneura-architecture` | `codex/scribe-optional-scheduling-contract` | `18e971e` | 3 | 3 |
| `~/Desktop/Cosmas/cosmaneura-sovereign-main` | `codex/v7-pilot-ux-remediation-plan` | `c570560` | dirty | dirty (unchanged) |

No bare `~/Desktop/Cosmas/sovereign` directory. Secrets/`.env` contents were not opened.

## What approval authorizes / does not

**Authorizes:** Roadmap Phase 1 foundation + Phase 2 vertical slice as one local synthetic mandate; Gate 1 internal checkpoint; local git init as above.

**Does not authorize:** Cloud deployment, real connectors, Track A changes, remotes/push, production credentials, Phase D2+.

## Stop line

Implementation waits for the exact owner message:

```text
APPROVE LOCAL SYNTH BUILD
```
