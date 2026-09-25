"""Install after the Inbox contract boundary; this adds only a private GET."""

import time
from uuid import UUID

from fastapi import Depends
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request

from cosmas_os.api import inbox_work_routes as base
from cosmas_os.application import inbox_review_options as options
from cosmas_os.application import inbox_work as inbox
from cosmas_os.application.workspace import WorkspaceError


def register(
    app,
    get_session,
    identity_dependency,
    *,
    policy_dependency=base.policy,
    registry_dependency=base.registry,
    reauthenticate=None,
):
    @app.get("/inbox/{item_id}/review-options")
    async def read(
        item_id: UUID,
        request: Request,
        s=Depends(get_session),
        identity=Depends(identity_dependency),
        gate=Depends(policy_dependency),
        installed=Depends(registry_dependency),
    ):
        def fence():
            if time.monotonic() >= getattr(request.state, "inbox_deadline", 0):
                inbox.error("inbox_unavailable", 503)
            s.expire_all()
            if reauthenticate is not None:
                reauthenticate(request, s, identity)
            else:
                current = identity_dependency(
                    session=s,
                    authorization=request.headers.get("authorization"),
                    x_box_id=request.headers.get("x-box-id"),
                    x_actor_principal_id=request.headers.get("x-actor-principal-id"),
                )
                if current != identity:
                    inbox.error("inbox_unavailable", 403)

        s.info["inbox_final_authority"] = fence
        try:
            await run_in_threadpool(fence)
            value = await run_in_threadpool(
                options.read,
                s,
                identity.box_id,
                identity.principal_id,
                str(item_id),
                registry=installed,
                policy=gate,
            )
            await run_in_threadpool(fence)
            return JSONResponse(value, headers={"Cache-Control": "no-store"})
        except WorkspaceError as exc:
            s.rollback()
            return base.failure(exc.code, exc.status)
        except SQLAlchemyError:
            s.rollback()
            return base.failure("inbox_unavailable", 503)
        finally:
            s.info.pop("inbox_final_authority", None)
