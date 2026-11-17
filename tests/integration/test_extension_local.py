"""Real signed JWT + local request, storage and recovery fences; no Clerk network."""
import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from cosmas_os.adapters.extension_observation_store import initialize_observations
from cosmas_os.api.auth import ClerkTokenVerifier
from cosmas_os.api.extension_local import create_app
from cosmas_os.extension_local_profile import API_ORIGIN, EXTENSION_ORIGIN, LocalExtensionProfile
from cosmas_os.models import ExternalIdentity, Principal


@pytest.fixture
def extension_case(session, seeded, monkeypatch):
    profile = LocalExtensionProfile("postgresql+psycopg://invented@127.0.0.1:54329/cosmabot_extension_synth",
        "https://invented-extension.clerk.accounts.dev", "org_invented", seeded["box_id"])
    runtime = profile.auth_settings()
    assert runtime.clerk_session_configuration_errors() == []
    initialize_observations(session.connection())
    binding = ExternalIdentity(box_id=profile.box_id, principal_id=seeded["owner_id"],
        provider="clerk", issuer=profile.issuer, subject="user_invented_extension",
        organization_id=profile.organization_id, reviewed_by="Invented reviewer", evidence_ref="test:extension")
    session.add(binding)
    session.commit()
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class LocalJwks:
        def get_signing_keys(self, *, refresh):
            return [SimpleNamespace(key_id="invented-key", key=key.public_key())]

    verifier = ClerkTokenVerifier(runtime, jwks_client=LocalJwks(), start_background_refresh=False)
    app = create_app(profile, lambda: session, verifier)
    monkeypatch.setattr(session, "close", lambda: None)
    monkeypatch.setattr(session.get_bind().engine, "hide_parameters", True)

    def token(**changes):
        now = datetime.now(UTC)
        claims = dict(iss=profile.issuer, sub="user_invented_extension", org_id=profile.organization_id,
            azp=EXTENSION_ORIGIN, sid="invented-session", iat=now, nbf=now, exp=now + timedelta(minutes=5))
        for name, value in changes.items():
            if value is None:
                claims.pop(name, None)
            else:
                claims[name] = value
        return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "invented-key"})

    with TestClient(app, base_url=API_ORIGIN, client=("127.0.0.1", 50000)) as client:
        yield SimpleNamespace(client=client, app=app, profile=profile, runtime=runtime, token=token,
                              binding=binding, session=session, actor=seeded["owner_id"])


def headers(case, **changes):
    return {"Origin": EXTENSION_ORIGIN, "Authorization": "Bearer " + case.token(**changes)}


def payload():
    return {"rows": [{"appointment": "invented-appt-" + str(uuid4()),
                      "person": "Invented Log Scrub Person", "time": "09:00"}]}


def count(case):
    return case.session.scalar(text("SELECT count(*) FROM extension_signin_proof.observations"))


def test_exact_origin_accepted_and_other_origins_refused_on_preflight_and_request(extension_case):
    case = extension_case
    assert case.client.get("/workspace/extension-session", headers=headers(case)).json()["signed_in"] is True
    for origin, expected in [(EXTENSION_ORIGIN, 200), ("chrome-extension://" + "a" * 32, 403),
        ("http://127.0.0.1:8765", 403), (EXTENSION_ORIGIN + "/", 403), ("null", 403)]:
        preflight = case.client.options("/workspace/screen-observations", headers={"Origin": origin,
            "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization,content-type"})
        assert preflight.status_code == expected
        actual = case.client.get("/workspace/extension-session", headers={**headers(case), "Origin": origin})
        assert actual.status_code == expected
        if expected == 200:
            assert actual.headers["access-control-allow-origin"] == EXTENSION_ORIGIN
        else:
            assert "access-control-allow-origin" not in actual.headers
    for extra in [{"Origin": ""}, {"Host": "other.invalid"}]:
        assert case.client.get("/workspace/extension-session", headers={**headers(case), **extra}).status_code == 403
    duplicate = list(headers(case).items()) + [("Origin", EXTENSION_ORIGIN)]
    assert case.client.get("/workspace/extension-session", headers=duplicate).status_code == 403
    with TestClient(case.app, base_url=API_ORIGIN, client=("198.51.100.20", 50000)) as remote:
        assert remote.get("/workspace/extension-session", headers=headers(case)).status_code == 403


@pytest.mark.parametrize("claims", [{"azp": None}, {"azp": "chrome-extension://" + "a" * 32},
    {"aud": "other"}, {"iss": "https://other.clerk.accounts.dev"}, {"exp": 1},
    {"sub": "user_unbound"}, {"org_id": "org_other"}, {"sid": None}])
def test_signed_claim_fences_and_empty_auth_fail_closed(extension_case, claims):
    case = extension_case
    body = payload()
    for path in ["/workspace/extension-session", "/workspace/screen-observations"]:
        response = case.client.request("GET" if path.endswith("session") else "POST", path,
            headers=headers(case, **claims), **({"json": body} if not path.endswith("session") else {}))
        assert response.status_code in {401, 403}
        assert "Invented Log Scrub Person" not in response.text
        assert response.headers["cache-control"] == "no-store"
    assert count(case) == 0


def test_unsigned_wrong_signature_and_spoofed_identity_cannot_call(extension_case):
    case = extension_case
    for auth in [None, "Bearer invented-invalid", "Basic invented", "Bearer " + jwt.encode({"sub": "user_invented_extension"}, "invented" * 8, algorithm="HS256")]:
        request_headers = {"Origin": EXTENSION_ORIGIN}
        if auth:
            request_headers["Authorization"] = auth
        assert case.client.get("/workspace/extension-session", headers=request_headers).status_code == 401
        assert case.client.post("/workspace/screen-observations", headers=request_headers, json=payload()).status_code == 401
    assert case.client.get("/workspace/extension-session", headers={**headers(case), "X-Box-Id": case.profile.box_id}).status_code == 401
    assert count(case) == 0


def test_log_scrub_generic_validation_storage_failure_and_recovery(extension_case, caplog, monkeypatch):
    case = extension_case
    body = payload()
    caplog.set_level(logging.INFO)
    accepted = case.client.post("/workspace/screen-observations", headers=headers(case), json=body)
    assert accepted.status_code == 200
    assert accepted.json()["payload_sha256"] == hashlib.sha256(json.dumps(body, sort_keys=True,
        separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    bad = {**body, "unexpected": body["rows"][0]["appointment"]}
    for value in [bad, {"rows": []}, {"rows": [{**body["rows"][0], "person": body["rows"][0]["person"] * 30}]}]:
        rejected = case.client.post("/workspace/screen-observations", headers=headers(case), json=value)
        assert rejected.status_code == 422
        assert rejected.json() == {"detail": "invalid_request"}
    with monkeypatch.context() as local:
        def fail(*args, **kwargs):
            raise RuntimeError(str(body))
        local.setattr("cosmas_os.api.extension_local.PostgresObservationStore.append", fail)
        failed = case.client.post("/workspace/screen-observations", headers=headers(case), json=body)
        assert failed.status_code == 503
        assert failed.json() == {"detail": "local_box_unavailable"}
    retry = case.client.post("/workspace/screen-observations", headers=headers(case), json=body)
    assert retry.status_code == 200
    assert retry.json()["observation_id"] != accepted.json()["observation_id"]
    assert count(case) == 2
    for value in body["rows"][0].values():
        if value == "09:00":
            continue
        assert value not in caplog.text
        for response in [accepted, rejected, failed, retry]:
            assert value not in response.text


def test_database_observations_cannot_update_delete_truncate_or_forge_hash(extension_case):
    case = extension_case
    assert case.client.post("/workspace/screen-observations", headers=headers(case), json=payload()).status_code == 200
    for sql in ["UPDATE extension_signin_proof.observations SET payload='changed'",
                "DELETE FROM extension_signin_proof.observations", "TRUNCATE extension_signin_proof.observations"]:
        with pytest.raises(DBAPIError), case.session.begin_nested():
            case.session.execute(text(sql))
        assert count(case) == 1
    with pytest.raises(DBAPIError), case.session.begin_nested():
        case.session.execute(text("""INSERT INTO extension_signin_proof.observations
            (id,box_id,principal_id,payload,payload_sha256) VALUES (:id,:box,:actor,'{}',:hash)"""),
            {"id": str(uuid4()), "box": case.profile.box_id, "actor": case.actor, "hash": "a" * 64})
    assert count(case) == 1


@pytest.mark.parametrize("revocation", ["binding", "human"])
def test_revocation_blocks_the_next_read_and_observation(extension_case, revocation):
    case = extension_case
    assert case.client.get("/workspace/extension-session", headers=headers(case)).status_code == 200
    if revocation == "binding":
        case.binding.active = False
    else:
        case.session.get(Principal, case.actor).state = "disabled"
    case.session.commit()
    assert case.client.get("/workspace/extension-session", headers=headers(case)).status_code == 403
    assert case.client.post("/workspace/screen-observations", headers=headers(case), json=payload()).status_code == 403
    assert count(case) == 0


def test_local_profile_refuses_hosted_databases_and_live_issuers(extension_case):
    case = extension_case
    for database, issuer in [("postgresql+psycopg://invented@remote.invalid:5432/cosmabot_extension_synth", case.profile.issuer),
        (case.profile.database_url.replace("cosmabot_extension_synth", "cosmas_os"), case.profile.issuer),
        (case.profile.database_url, "https://clerk.cosmas.ai")]:
        with pytest.raises(ValueError, match="local_extension_profile_refused"):
            LocalExtensionProfile(database, issuer, case.profile.organization_id, case.profile.box_id)
