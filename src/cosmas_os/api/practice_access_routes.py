"""Bounded signed-in member enrollment; no general administrative API passthrough."""

import asyncio
import json

from fastapi.responses import Response
from pydantic import ValidationError
from starlette.requests import Request

from cosmas_os.api.auth import AccessDenied, AuthenticationFailed, _organization_id
from cosmas_os.api.practice_access_schemas import (
    CompletePracticeSetup,
    DecideAccess,
    MemberChange,
    MembersPage,
    ReviewAccess,
    SubmitAccess,
)
from cosmas_os.api.workspace_protocol import compatibility
from cosmas_os.application import practice_access as access
from cosmas_os.application import practice_members, practice_setup
from cosmas_os.application.beta_identity_admin import BetaIdentityAdminError
from cosmas_os.application.capture_deadline import (
    CaptureBudget,
    capture_budget,
    check_capture_deadline,
    run_in_threadpool,
)
from cosmas_os.domain.rules import AuthorizationError

PATHS = {"/practice-access/compatibility": ("GET", None, compatibility),
         "/practice-access": ("GET", None, access.status),
         "/practice-access/setup": ("GET", None, practice_setup.status),
         "/practice-access/setup/complete": ("POST", CompletePracticeSetup, practice_setup.complete),
         "/practice-access/request": ("POST", SubmitAccess, access.submit),
         "/practice-access/cancel": ("POST", ReviewAccess, access.cancel),
         "/practice-access/requests": ("GET", None, access.pending),
         "/practice-access/decide": ("POST", DecideAccess, access.decide),
         "/practice-access/members": ("POST", MembersPage, practice_members.members),
         "/practice-access/member-change": ("POST", MemberChange, practice_members.change)}


def response(value, status=200):
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    if len(raw) > 131072:
        return response({"detail": "practice_access_unavailable"}, 503)
    return Response(raw, status_code=status, media_type="application/json",
                    headers={"Cache-Control": "no-store"})


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate request field")
        value[key] = item
    return value


def verified(runtime, authorization, verifier):
    if (runtime.auth_mode != "clerk_jwt" or not isinstance(authorization, str)
            or not authorization.startswith("Bearer ") or len(authorization) > 8200):
        raise AuthenticationFailed()
    claims = verifier.verify(authorization[7:])
    subject = claims.get("sub")
    if (claims.get("iss") != runtime.clerk_issuer or not isinstance(subject, str)
            or not subject.startswith("user_") or len(subject) > 255
            or _organization_id(claims) != runtime.clerk_organization_id):
        raise AccessDenied()
    return access.VerifiedMember(runtime.beta_box_id, runtime.clerk_issuer,
                                 runtime.clerk_organization_id, subject)


def register(app, *, runtime, verifier, session_factory):
    async def dispatch(request: Request):
        spec = PATHS.get(request.url.path)
        if spec is None:
            return response({"detail": "practice_access_not_found"}, 404)
        method, model, operation = spec
        if request.method != method:
            return response({"detail": "invalid_practice_access_request"}, 405)
        if request.headers.getlist("x-cosmas-practice-access-contract") != ["1"]:
            return response({"detail": "practice_access_contract_required"}, 426)
        if (request.scope.get("query_string") or request.headers.getlist("content-encoding")
                or request.headers.getlist("transfer-encoding")
                or request.headers.getlist("x-box-id") or request.headers.getlist("x-actor-principal-id")
                or len(request.headers.getlist("authorization")) != 1
                or method == "POST" and request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json"):
            return response({"detail": "invalid_practice_access_request"}, 422)
        try:
            body = bytearray()
            async with asyncio.timeout(15):
                async for chunk in request.stream():
                    if len(body) + len(chunk) > 4096 or method == "GET" and chunk:
                        raise ValueError
                    body.extend(chunk)
            command = model.model_validate(json.loads(body, object_pairs_hook=_unique)) if model else None

            def invoke():
                config = runtime()
                if not config.workspace_hosted_enabled or not config.workspace_available:
                    raise access.PracticeAccessError("practice_access_not_found", 404)
                token_verifier = verifier(request.headers.getlist("origin"))
                member = verified(config, request.headers["authorization"], token_verifier)

                def fence():
                    check_capture_deadline()
                    if (runtime() is not config or not config.workspace_hosted_enabled
                            or not config.workspace_available
                            or verified(config, request.headers["authorization"], token_verifier) != member):
                        raise AccessDenied()

                with session_factory() as session:
                    try:
                        if command is None:
                            result = operation(session, config, member, fence=fence)
                        else:
                            result = operation(session, config, member, command, fence=fence)
                        return result
                    except BaseException:
                        session.rollback()
                        raise

            with capture_budget(CaptureBudget(15)):
                result = await run_in_threadpool(invoke)
            return response(result)
        except AuthenticationFailed:
            return response({"detail": "practice_access_authentication_required"}, 401)
        except (AccessDenied, AuthorizationError):
            return response({"detail": "practice_access_denied"}, 403)
        except access.PracticeAccessError as error:
            return response({"detail": error.code}, error.status)
        except BetaIdentityAdminError:
            return response({"detail": "practice_access_conflict"}, 409)
        except (ValueError, TypeError, ValidationError):
            return response({"detail": "invalid_practice_access_request"}, 422)
        except TimeoutError:
            return response({"detail": "practice_access_timeout"}, 504)
        except Exception:
            return response({"detail": "practice_access_unavailable"}, 503)

    @app.middleware("http")
    async def boundary(request, call_next):
        if request.method == "OPTIONS" or not (
            request.url.path == "/practice-access" or request.url.path.startswith("/practice-access/")
        ):
            return await call_next(request)
        return await dispatch(request)

    for path, (method, _, _) in PATHS.items():
        app.add_api_route(path, dispatch, methods=[method], tags=["practice-access"])
