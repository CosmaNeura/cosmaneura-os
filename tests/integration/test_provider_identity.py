"""Real signed verifier + PostgreSQL through the installed main-app account read."""

import json
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from cosmas_os.api import app as api
from cosmas_os.api import provider_identity_routes as route
from cosmas_os.api.auth import ClerkTokenVerifier
from cosmas_os.application import workspace as ws
from cosmas_os.config import Settings
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.models import ExternalIdentity, Principal, Ticket

PATH = "/provider-team/identity"
ORIGIN = "http://localhost:5173"


@pytest.fixture
def signed(session, seeded, monkeypatch):
    box, owner = seeded["box_id"], seeded["owner_id"]
    conf = Settings(
        _env_file=None,
        workspace_enabled=True,
        workspace_authenticated_enabled=True,
        workspace_draft_recovery_required=True,
        auth_mode="clerk_jwt",
        synth_seed=False,
        clerk_issuer="https://identity.example.invalid",
        clerk_jwks_url="https://identity.example.invalid/.well-known/jwks.json",
        clerk_audience="cosmas-identity-local",
        clerk_organization_id="org_identity_invented",
        clerk_authorized_parties=ORIGIN,
        beta_box_id=box,
        cors_allowed_origins=ORIGIN,
    )
    monkeypatch.setattr(api, "settings", conf)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class OfflineKeys:
        def get_signing_keys(self, *, refresh):
            return [SimpleNamespace(key_id="identity-test-key", key=key.public_key())]

    verifier = ClerkTokenVerifier(conf, jwks_client=OfflineKeys(), start_background_refresh=False)
    monkeypatch.setattr(api, "_clerk_verifier", lambda: verifier)
    people = {"owner": owner}
    bindings = {}
    for label, is_owner in [("staff", False), ("peer", True)]:
        p = Principal(
            box_id=box,
            principal_type="human",
            display_name="Invented " + label,
            state="active",
            is_owner=is_owner,
        )
        session.add(p)
        session.flush()
        people[label] = p.id
    for label, actor in people.items():
        binding = ExternalIdentity(
            box_id=box,
            principal_id=actor,
            provider="clerk",
            issuer=conf.clerk_issuer,
            subject="user_identity_" + label,
            organization_id=conf.clerk_organization_id,
            reviewed_by="Invented reviewer",
            evidence_ref="test:identity-binding",
        )
        session.add(binding)
        bindings[label] = binding
    session.commit()

    def token(label="owner", **changes):
        now = datetime.now(UTC)
        claims = dict(
            sub="user_identity_" + label,
            iss=conf.clerk_issuer,
            aud=conf.clerk_audience,
            sid="session_identity",
            azp=ORIGIN,
            org_id=conf.clerk_organization_id,
            iat=now,
            nbf=now,
            exp=now + timedelta(minutes=5),
        )
        return jwt.encode(
            {**claims, **changes}, key, algorithm="RS256", headers={"kid": "identity-test-key"}
        )

    def headers(label="owner", **changes):
        return {
            "Authorization": "Bearer " + token(label, **changes),
            "X-Cosmas-Team-Contract": "2",
            "X-Cosmas-Draft-Recovery": "2",
            "Origin": ORIGIN,
        }

    def get_session():
        yield session

    api.app.dependency_overrides[api.get_session] = get_session
    try:
        with TestClient(api.app) as client:
            yield SimpleNamespace(
                client=client,
                box=box,
                people=people,
                bindings=bindings,
                headers=headers,
                configuration=conf,
                token=token,
            )
    finally:
        api.app.dependency_overrides.pop(api.get_session, None)


def check(response, status=200, code=None, *, origin=ORIGIN):
    assert response.status_code == status, response.text
    assert response.headers["cache-control"] == "no-store"
    assert len(response.content) <= 1024
    assert response.headers.get("access-control-allow-origin") == origin
    value = response.json()
    if code:
        assert value == {"detail": code}
    return value


def test_owner_staff_and_peer_get_only_their_signed_context_without_any_patient(
    signed, session, tmp_path
):
    c = signed
    assert session.scalar(select(func.count()).select_from(Ticket).where(Ticket.box_id == c.box)) == 0
    vectors = {}
    for role in ("owner", "staff", "peer"):
        value = check(c.client.get(PATH, headers=c.headers(role)))
        assert value == {
            "contract_version": 1,
            "box_id": c.box,
            "actor_id": c.people[role],
            "recovery_scope": payload_hash(
                {
                    "contract": "cosmas-private-drafts-v1",
                    "box_id": c.box,
                    "owner_id": c.people[role],
                }
            ),
        }
        team = c.client.get("/provider-team", headers=c.headers(role))
        assert team.status_code == 200 and team.json()["recovery_scope"] == value["recovery_scope"]
        assert check(c.client.get(PATH, headers=c.headers(role, sid="new-session"))) == value
        vectors[role] = {"status": 200, "headers": {"cache-control": "no-store"}, "body": value}
    c.bindings["staff"].active = False
    session.commit()
    value = check(c.client.get(PATH, headers=c.headers("staff")), 403, "identity_access_denied")
    vectors["disabled_identity"] = {
        "status": 403,
        "headers": {"cache-control": "no-store"},
        "body": value,
    }
    (tmp_path / "actual-account-identity-http.json").write_text(
        json.dumps(vectors, indent=2) + "\n"
    )
    assert session.scalar(select(func.count()).select_from(Ticket).where(Ticket.box_id == c.box)) == 0


@pytest.mark.parametrize(
    "changes,status",
    [
        ({"sub": "user_unprovisioned"}, 403),
        ({"org_id": "org_other"}, 403),
        ({"aud": "wrong"}, 401),
        ({"azp": "http://foreign.invalid"}, 401),
        ({"exp": datetime(2000, 1, 1, tzinfo=UTC)}, 401),
    ],
)
def test_signed_authority_rejections(signed, changes, status):
    check(
        signed.client.get(PATH, headers=signed.headers(**changes)),
        status,
        "identity_access_denied" if status == 403 else "identity_authentication_required",
    )


@pytest.mark.parametrize("change", ["binding", "human", "nonhuman", "tombstone", "configured_box"])
def test_current_authority_revocation_withholds_all_context(signed, session, change):
    c = signed
    check(c.client.get(PATH, headers=c.headers()))
    if change == "binding":
        c.bindings["owner"].active = False
    elif change == "configured_box":
        c.configuration.beta_box_id = c.people["staff"]
    elif change == "human":
        session.get(Principal, c.people["owner"]).state = "disabled"
    elif change == "nonhuman":
        session.get(Principal, c.people["owner"]).principal_type = "agent"
    else:
        session.get(Principal, c.people["owner"]).tombstoned_at = datetime.now(UTC)
    session.commit()
    check(c.client.get(PATH, headers=c.headers()), 403, "identity_access_denied")


@pytest.mark.parametrize("stage", ["before_read", "before_disclosure"])
def test_fresh_reauthentication_rejects_revocation_during_read(signed, session, monkeypatch, stage):
    c = signed
    if stage == "before_read":
        original = api._identity

        # The route dependency retains the original function. Reauthentication
        # resolves api._identity afresh and must observe this lost binding.
        def revoke(**kw):
            c.bindings["owner"].active = False
            session.commit()
            return original(**kw)

        monkeypatch.setattr(api, "_identity", revoke)
    else:
        original = route.IdentityContext.model_validate

        def validate(value):
            result = original(value)
            c.bindings["owner"].active = False
            session.commit()
            return result

        monkeypatch.setattr(route.IdentityContext, "model_validate", validate)
    check(c.client.get(PATH, headers=c.headers()), 403, "identity_access_denied")


@pytest.mark.parametrize("header", [None, "1", "3", "2, 2"])
def test_exact_required_contract(signed, header):
    headers = signed.headers()
    headers.pop("X-Cosmas-Team-Contract")
    if header is not None:
        headers["X-Cosmas-Team-Contract"] = header
    check(signed.client.get(PATH, headers=headers), 426, "team_contract_required")


@pytest.mark.parametrize(
    "name", ["X-Cosmas-Team-Contract", "Authorization", "X-Cosmas-Draft-Recovery", "Content-Length"]
)
def test_duplicate_authority_and_framing_are_rejected(signed, name):
    headers = list(signed.headers().items())
    if name == "Content-Length":
        headers += [(name, "0"), (name, "0")]
    else:
        headers.append((name, dict(headers)[name]))
    status, code = (
        (426, "team_contract_required")
        if name == "X-Cosmas-Team-Contract"
        else (426, "workspace_client_update_required")
        if name == "X-Cosmas-Draft-Recovery"
        else (422, "invalid_identity_request")
    )
    check(signed.client.get(PATH, headers=headers), status, code)


@pytest.mark.parametrize(
    "suffix,extra,body",
    [
        ("?actor_id=foreign", {}, b""),
        ("?token=secret", {}, b""),
        ("", {"Content-Encoding": ""}, b""),
        ("", {"Transfer-Encoding": ""}, b""),
        ("", {}, b"{}"),
        ("", {"Content-Length": "0"}, b"undeclared"),
        ("", {"Content-Length": "garbage"}, b""),
        ("", {"Content-Length": "99999999999999999"}, b""),
    ],
)
def test_no_query_body_or_encoding(signed, suffix, extra, body):
    check(
        signed.client.request("GET", PATH + suffix, headers=signed.headers() | extra, content=body),
        422,
        "invalid_identity_request",
    )


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH", "HEAD"])
def test_no_commands(signed, method):
    response = signed.client.request(method, PATH, headers=signed.headers())
    assert response.status_code == 405 and response.headers["cache-control"] == "no-store"
    assert len(response.content) <= 1024


def test_unknown_suffix_and_missing_auth_are_private(signed):
    check(
        signed.client.get(PATH + "/unknown", headers=signed.headers()), 404, "identity_unavailable"
    )
    h = signed.headers()
    h.pop("Authorization")
    check(signed.client.get(PATH, headers=h), 401, "identity_authentication_required")
    check(
        signed.client.get(PATH, headers=signed.headers() | {"X-Box-Id": signed.box}),
        401,
        "identity_authentication_required",
    )


def test_existing_workspace_gates_remain_required(signed):
    h = signed.headers()
    h.pop("X-Cosmas-Draft-Recovery")
    check(signed.client.get(PATH, headers=h), 426, "workspace_client_update_required")
    signed.configuration.workspace_enabled = False
    check(signed.client.get(PATH, headers=signed.headers()), 404, "identity_unavailable")


def test_synthetic_header_mode_does_not_supply_signed_account_identity(signed):
    signed.configuration.auth_mode = "synth_headers"
    signed.configuration.workspace_authenticated_enabled = False
    headers = {
        "X-Box-Id": signed.box,
        "X-Actor-Principal-Id": signed.people["owner"],
        "X-Cosmas-Team-Contract": "2",
        "X-Cosmas-Draft-Recovery": "2",
        "Origin": ORIGIN,
    }
    check(signed.client.get(PATH, headers=headers), 403, "identity_access_denied")


def test_closed_response_rejects_corrupt_scope_without_disclosure(signed, monkeypatch):
    original = route.IdentityContext.model_validate
    monkeypatch.setattr(
        route.IdentityContext,
        "model_validate",
        lambda value: original(value | {"recovery_scope": "bad"}),
    )
    check(signed.client.get(PATH, headers=signed.headers()), 503, "identity_unavailable")


def test_deadline_fences_stalled_read_without_disclosure(signed, monkeypatch):
    original = ws._human
    calls = []

    def stalled(*args, **kwargs):
        calls.append(True)
        time.sleep(0.03)
        return original(*args, **kwargs)

    monkeypatch.setattr(route, "DEADLINE_SECONDS", 0.01)
    monkeypatch.setattr(ws, "_human", stalled)
    check(signed.client.get(PATH, headers=signed.headers()), 504, "identity_timeout")
    assert len(calls) == 1


def test_cors_preflight_and_unknown_origin(signed):
    h = {
        "Origin": ORIGIN,
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "authorization,x-cosmas-team-contract,x-cosmas-draft-recovery",
    }
    allowed = signed.client.options(PATH, headers=h)
    assert allowed.status_code == 200 and allowed.headers["access-control-allow-origin"] == ORIGIN
    denied = signed.client.options(PATH, headers=h | {"Origin": "https://unknown.invalid"})
    assert denied.status_code == 400 and "access-control-allow-origin" not in denied.headers
    check(
        signed.client.get(PATH, headers=signed.headers() | {"Origin": "https://unknown.invalid"}),
        origin=None,
    )


@pytest.mark.parametrize("value", [None, "1", "3", "2, 2"])
def test_identity_requires_exact_recovery_header_even_when_broader_gate_optional(signed, value):
    signed.configuration.workspace_draft_recovery_required = False
    headers = signed.headers()
    headers.pop("X-Cosmas-Draft-Recovery")
    if value is not None:
        headers["X-Cosmas-Draft-Recovery"] = value
    check(signed.client.get(PATH, headers=headers), 426, "workspace_client_update_required")
