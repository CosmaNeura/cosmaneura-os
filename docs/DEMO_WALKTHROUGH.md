# Demo walkthrough — Insurance ArtifactChase L0

## Prerequisites

```bash
docker-compose up -d postgres redis
uv sync --extra dev
uv run alembic upgrade head
```

## CLI path (deterministic)

```bash
uv run python -m cosmas_os.cli demo-artifact-chase
```

Expected JSON fields: `ticket_state=closed`, `coverage=image_on_file`,
non-empty `purge_receipts`, `timeline_events >= 4`.

## Interactive path

1. `./scripts/dev-up.sh`
2. `cd web && pnpm install && pnpm dev`
3. If the queue is empty, run the demo CLI once, then refresh the UI.
4. For a pending item: Approve (or Edit → Approve, Reject, Escalate).
5. After send/confirm flows (CLI covers upload/verify), Close and Show history.

## What you should not see

`box_id`, operation IDs, Celery, Redis, or compliance jargon on the primary queue.
