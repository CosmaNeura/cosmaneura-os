"""Bounded signed-in member enrollment; no general administrative API passthrough."""

import asyncio
import json

from fastapi.responses import Response
from pydantic import ValidationError
from starlette.requests import Request

from cosmas_os.adapters.enrollment_admission import (
    ACCESS_REQUIRED,
    RuntimeAdmissionError,
    existing_user_admission,
    require_runtime_admission,
)
from cosmas_os.api.auth import (
    AccessDenied,
    AuthenticationFailed,
    _organization_id,
    native_clerk_origin,
)
from cosmas_os.api.practice_access_schemas import (
    CompletePracticeSetup,
    CreateInvitation,
    DecideAccess,
    JoinInvitation,
    MemberChange,
    MembersPage,
    ReviewAccess,
    RevokeInvitation,
    SubmitAccess,
)
from cosmas_os.api.workspace_protocol import compatibility
from cosmas_os.application import practice_access as access
from cosmas_os.application import practice_invites, practice_members, practice_setup
from cosmas_os.application.beta_identity_admin import BetaIdentityAdminError
from cosmas_os.application.capture_deadline import (
    CaptureBudget,
    capture_budget,
    check_capture_deadline,
    run_in_threadpool,
)
from cosmas_os.application.enrollment_access import prepare_registered_member
from cosmas_os.domain.rules import AuthorizationError
from cosmas_os.practice_setup_models import PracticeSetupProfile

PATHS = {"/practice-access/invitations": ("GET", None, practice_invites.list_invitations),
         "/practice-access/invitation/create/resolve": ("POST", CreateInvitation, practice_invites.resolve_create),
         "/practice-access/invitation/revoke/resolve": ("POST", RevokeInvitation, practice_invites.resolve_revoke),
         "/practice-access/invitation/create": ("POST", CreateInvitation, practice_invites.create),
         "/practice-access/invitation/revoke": ("POST", RevokeInvitation, practice_invites.revoke),
         "/practice-access/invitation/join": ("POST", JoinInvitation, practice_invites.join),
         "/practice-access/compatibility": ("GET", None, compatibility),
         "/practice-access": ("GET", None, access.status),
         "/practice-access/enrollment-qualification": ("GET", None, access.enrollment_qualification),
         "/practice-access/native-qualification": ("GET", None, access.enrollment_qualification),
         "/practice-access/setup": ("GET", None, practice_setup.status),
         "/practice-access/setup/complete": ("POST", CompletePracticeSetup, practice_setup.complete),
         "/practice-access/request": ("POST", SubmitAccess, access.submit),
         "/practice-access/cancel": ("POST", ReviewAccess, access.cancel),
         "/practice-access/requests": ("GET", None, access.pending),
         "/practice-access/decide": ("POST", DecideAccess, access.decide),
         "/practice-access/members": ("POST", MembersPage, practice_members.members),
         "/practice-access/member-change": ("POST", MemberChange, practice_members.change)}


def response(value, status=200, headers=None):
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    if len(raw) > 131072:
        return response({"detail": "practice_access_unavailable"}, 503)
    return Response(raw, status_code=status, media_type="application/json",
                    headers={"Cache-Control": "no-store", **(headers or {})})


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


def _native_qualification(runtime, origins, authorization, verifier, session_factory):
    """Measure local native transport and setup; grants no enrollment admission.

    This read does not call central enrollment: central qualification measures it,
    so doing so would recurse. Workspace routes retain their admission checks.
    Retention/legal hooks belong in enrollment, not in this transport receipt.
    """
    config = runtime()
    origin = native_clerk_origin(config, origins)
    if origin is None:
        raise access.PracticeAccessError("practice_access_not_found", 404)
    checked = verifier(origins)
    member = verified(config, authorization, checked)
    session_id = checked.verify(authorization[7:]).get("sid")
    if (not isinstance(session_id, str) or not session_id.startswith("sess_")
            or len(session_id) > 255):
        raise AuthenticationFailed()
    with session_factory() as session:
        principal = access._binding(session, member)
        if principal is None or session.get(PracticeSetupProfile, member.box_id) is None:
            raise access.PracticeAccessError("practice_access_denied", 403)
        principal_id = principal.id

        def fence():
            check_capture_deadline()
            if (runtime() is not config or native_clerk_origin(config, origins) != origin
                    or verified(config, authorization, checked) != member
                    or checked.verify(authorization[7:]).get("sid") != session_id):
                raise AccessDenied()
            current = access._binding(session, member)
            if (current is None or current.id != principal_id
                    or session.get(PracticeSetupProfile, member.box_id,
                                   populate_existing=True) is None):
                raise AccessDenied()

        result = access.enrollment_qualification(session, config, member, fence=fence)
        fence()
        return {**result, "native_origin": origin, "session_id": session_id,
                "initial_setup_complete": True}


def register(app, *, runtime, verifier, session_factory, admission_adapter=None,
             native_admission_adapter=None):
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
            def invoke():
                if request.url.path == "/practice-access/native-qualification":
                    return _native_qualification(
                        runtime, request.headers.getlist("origin"),
                        request.headers["authorization"], verifier, session_factory)
                config = runtime()
                if ((not config.workspace_hosted_enabled and config.cosmas_env != "standalone_synthetic")
                        or not config.workspace_available):
                    raise access.PracticeAccessError("practice_access_not_found", 404)
                token_verifier = verifier(request.headers.getlist("origin"))
                member = verified(config, request.headers["authorization"], token_verifier)
                purpose = "qualification" if request.url.path in {"/practice-access/enrollment-qualification", "/practice-access/setup", "/practice-access/setup/complete"} else "workspace"

                def selected_adapter():
                    origins = request.headers.getlist("origin")
                    if (native_admission_adapter is not None
                            and native_clerk_origin(config, origins) is not None):
                        return native_admission_adapter(origins)
                    return admission_adapter() if admission_adapter else None

                def fence():
                    check_capture_deadline()
                    if (runtime() is not config or (not config.workspace_hosted_enabled
                            and config.cosmas_env != "standalone_synthetic")
                            or not config.workspace_available
                            or verified(config, request.headers["authorization"], token_verifier) != member):
                        raise AccessDenied()
                    if getattr(config, "workspace_enrollment_managed", False):
                        current_principal = access._binding(session, member, lock=False)
                        if (checked_admission is not None and checked_admission.get("existing_user") is True
                                and initial_principal_id is not None
                                and (current_principal is None or current_principal.id != initial_principal_id)):
                            raise AccessDenied()
                    if checked_admission is not None and checked_admission.get("existing_user") is True:
                        # Retain the verified initial history classification;
                        # local authority changes never turn it into enrollment.
                        return
                    current_admission = require_runtime_admission(config, request.headers["authorization"], member.subject,
                        purpose=purpose, adapter=selected_adapter(), session=session)
                    if (checked_admission is not None and checked_admission.get("existing_user") is not True and (current_admission is None
                            or current_admission["member_role"] != checked_admission["member_role"]
                            or current_admission["display_name"] != checked_admission["display_name"])):
                        raise RuntimeAdmissionError(ACCESS_REQUIRED, 403)

                with session_factory() as session:
                    try:
                        existing = None
                        initial_principal_id = None
                        if getattr(config, "workspace_enrollment_managed", False):
                            # Preserve revoked/remapped local identity denials;
                            # enrollment cannot repair or reinterpret those records.
                            # The operation retains its existing Box-first locks.
                            initial_principal = access._binding(session, member, lock=False)
                            initial_principal_id = initial_principal.id if initial_principal is not None else None
                            existing = existing_user_admission(session, config, member.subject)
                        if (getattr(config, "workspace_enrollment_managed", False) and existing is None
                                and method == "POST" and request.url.path not in {"/practice-access/setup/complete", "/practice-access/members"}):
                            raise RuntimeAdmissionError(ACCESS_REQUIRED, 403)
                        checked_admission = existing if existing is not None else require_runtime_admission(
                            config, request.headers["authorization"], member.subject, purpose=purpose,
                            adapter=selected_adapter(), session=session)
                        if (getattr(config, "workspace_enrollment_managed", False)
                                and (checked_admission is None or checked_admission.get("existing_user") is not True)
                                and request.url.path == "/practice-access/setup/complete"
                                and (checked_admission is None or checked_admission["member_role"] != "owner")):
                            raise RuntimeAdmissionError(ACCESS_REQUIRED, 403)
                        command = model.model_validate(json.loads(body, object_pairs_hook=_unique)) if model else None
                        if request.url.path == "/practice-access/enrollment-qualification":
                            prepare_registered_member(session, config, member, checked_admission, fence=fence)
                        if command is None:
                            result = operation(session, config, member, fence=fence)
                        else:
                            result = operation(session, config, member, command, fence=fence)
                        if (request.url.path == "/practice-access/enrollment-qualification" and checked_admission is not None
                                and checked_admission.get("existing_user") is not True):
                            marker = {k: checked_admission[k] for k in ("contract_version", "enforced", "practice_id", "purpose")}
                            result = {**result, "enrollment_admission": marker,
                                      "initial_setup_complete": session.get(PracticeSetupProfile, member.box_id) is not None}
                        return result
                    except BaseException:
                        session.rollback()
                        raise

            with capture_budget(CaptureBudget(15)):
                result = await run_in_threadpool(invoke)
            headers = ({"X-Cosmas-Workspace-Protocol": "1"}
                       if request.url.path == "/practice-access/native-qualification" else None)
            return response(result, headers=headers)
        except AuthenticationFailed:
            return response({"detail": "practice_access_authentication_required"}, 401)
        except RuntimeAdmissionError as error:
            return response({"detail": error.code}, error.status, error.headers)
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
