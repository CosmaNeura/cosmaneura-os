from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

import cosmas_os.api.auth as auth_module
from cosmas_os.api.auth import AccessDenied, AuthenticationFailed, ClerkTokenVerifier
from cosmas_os.config import Settings


def _settings(**overrides) -> Settings:
    values = {
        "cosmas_env": "early_adopter_beta",
        "auth_mode": "clerk_jwt",
        "cors_allowed_origins": "https://beta.example.invalid",
        "synth_seed": False,
        "blob_backend": "azure",
        "azure_storage_account_url": "https://storage.example.invalid",
        "azure_blob_container": "box-data",
        "clerk_issuer": "https://clerk.example.invalid",
        "clerk_jwks_url": "https://clerk.example.invalid/.well-known/jwks.json",
        "clerk_audience": "cosmas-beta-api",
        "clerk_organization_id": "org_test_beta",
        "clerk_authorized_parties": "https://beta.example.invalid",
        "beta_box_id": "00000000-0000-4000-8000-000000000001",
        "clinic_approval_ref": "approval:test-clinic",
        "baa_evidence_ref": "baa:test-evidence",
        "human_deploy_evidence_ref": "deploy:test-review",
        "database_url": (
            "postgresql+psycopg://test:test@pg.example.invalid/cosmas_os?"
            "sslmode=verify-full&sslrootcert=system"
        ),
        "redis_url": "rediss://:invented-secret@redis.example.invalid:6380/0?ssl_cert_reqs=required",
        "sync_worker": False,
    }
    values.update(overrides)
    return Settings(**values)


def _token(
    private_key,
    *,
    kid: str = "test-key",
    omit: tuple[str, ...] = (),
    **claim_overrides,
) -> str:
    now = datetime.now(UTC)
    claims = {
        "iss": "https://clerk.example.invalid",
        "sub": "user_test_owner",
        "sid": "sess_test_owner",
        "azp": "https://beta.example.invalid",
        "aud": "cosmas-beta-api",
        "iat": now,
        "nbf": now - timedelta(seconds=1),
        "exp": now + timedelta(minutes=5),
        "o": {"id": "org_test_beta"},
    }
    claims.update(claim_overrides)
    for claim in omit:
        claims.pop(claim, None)
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": kid})


def _verifier():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwks = SimpleNamespace(
        get_signing_keys=lambda **_: [
            SimpleNamespace(key_id="test-key", key=private_key.public_key())
        ]
    )
    verifier = ClerkTokenVerifier(
        _settings(), jwks_client=jwks, start_background_refresh=False
    )
    return private_key, verifier


def test_clerk_verifier_accepts_signed_session_for_exact_org_and_origin() -> None:
    private_key, verifier = _verifier()
    claims = verifier.verify(_token(private_key))
    assert claims["sub"] == "user_test_owner"


def test_clerk_verifier_rejects_wrong_org_and_origin() -> None:
    private_key, verifier = _verifier()
    with pytest.raises(AccessDenied):
        verifier.verify(_token(private_key, o={"id": "org_wrong"}))
    with pytest.raises(AuthenticationFailed):
        verifier.verify(_token(private_key, azp="https://evil.example.invalid"))


def test_clerk_verifier_requires_configured_matching_audience() -> None:
    with pytest.raises(RuntimeError, match="configuration is incomplete"):
        ClerkTokenVerifier(_settings(clerk_audience=None))

    private_key, verifier = _verifier()
    with pytest.raises(AuthenticationFailed):
        verifier.verify(_token(private_key, aud="another-api"))
    with pytest.raises(AuthenticationFailed):
        verifier.verify(_token(private_key, omit=("aud",)))


def test_clerk_verifier_rejects_conflicting_org_claim_shapes() -> None:
    private_key, verifier = _verifier()
    with pytest.raises(AccessDenied):
        verifier.verify(
            _token(private_key, org_id="org_other", o={"id": "org_test_beta"})
        )


def test_clerk_verifier_rejects_non_rs256_algorithm_before_key_lookup() -> None:
    _, verifier = _verifier()
    token = jwt.encode(
        {"sub": "user_test_owner"},
        "test-secret-that-is-at-least-32-bytes-long",
        algorithm="HS256",
        headers={"kid": "test-key"},
    )
    with pytest.raises(AuthenticationFailed):
        verifier.verify(token)


def test_unknown_kids_never_drive_remote_refresh_and_cache_is_bounded(monkeypatch) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = [100.0]
    monkeypatch.setattr("cosmas_os.api.auth.monotonic", lambda: now[0])

    class StaticKeys:
        calls = 0

        def get_signing_keys(self, **_: object):
            self.calls += 1
            return [SimpleNamespace(key_id="test-key", key=private_key.public_key())]

    keys = StaticKeys()
    verifier = ClerkTokenVerifier(
        _settings(), jwks_client=keys, start_background_refresh=False
    )

    def reject(index: int) -> None:
        with pytest.raises(AuthenticationFailed):
            verifier.verify(_token(private_key, kid=f"unknown-{index}"))

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(reject, range(verifier._KID_CACHE_LIMIT + 16)))

    now[0] += verifier._UNKNOWN_KID_TTL_SECONDS + 1
    reject(verifier._KID_CACHE_LIMIT + 17)

    assert keys.calls == 1
    assert len(verifier._unknown_kids) == verifier._KID_CACHE_LIMIT


def test_concurrent_cold_start_shares_one_fetch_and_refresh_loop(monkeypatch) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ready = Barrier(16)
    fetch_started = Event()
    release_fetch = Event()
    client_constructions: list[str] = []
    fetches: list[bool] = []
    refresh_threads: list[str] = []

    class BlockingKeys:
        def get_signing_keys(self, **_: object):
            fetches.append(True)
            fetch_started.set()
            assert release_fetch.wait(timeout=1)
            return [SimpleNamespace(key_id="test-key", key=private_key.public_key())]

    def fake_jwks_client(url: str, **_: object) -> BlockingKeys:
        client_constructions.append(url)
        return BlockingKeys()

    class FakeThread:
        def __init__(self, *, name: str, **_: object) -> None:
            self.name = name

        def start(self) -> None:
            refresh_threads.append(self.name)

    monkeypatch.setattr(ClerkTokenVerifier, "_shared_states", {})
    monkeypatch.setattr(auth_module, "PyJWKClient", fake_jwks_client)
    monkeypatch.setattr(auth_module, "Thread", FakeThread)
    runtime_settings = _settings(
        clerk_issuer="https://cold-start.example.invalid",
        clerk_jwks_url="https://cold-start.example.invalid/.well-known/jwks.json",
    )

    def construct(_: int) -> ClerkTokenVerifier:
        ready.wait(timeout=1)
        return ClerkTokenVerifier(runtime_settings)

    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = [pool.submit(construct, index) for index in range(16)]
        assert fetch_started.wait(timeout=1)
        try:
            assert len(client_constructions) == 1
            assert len(fetches) == 1
        finally:
            release_fetch.set()
        verifiers = [future.result(timeout=1) for future in futures]

    assert len(refresh_threads) == 1
    assert len({id(verifier._signing_keys) for verifier in verifiers}) == 1


def test_oversized_kid_is_rejected_before_key_lookup() -> None:
    private_key, verifier = _verifier()

    with pytest.raises(AuthenticationFailed):
        verifier.verify(_token(private_key, kid="x" * 256))


def test_known_kid_remains_available_during_unknown_kid_backoff() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class MixedKeys:
        calls = 0

        def get_signing_keys(self, **_: object):
            self.calls += 1
            return [SimpleNamespace(key_id="test-key", key=private_key.public_key())]

    keys = MixedKeys()
    verifier = ClerkTokenVerifier(
        _settings(), jwks_client=keys, start_background_refresh=False
    )

    with pytest.raises(AuthenticationFailed):
        verifier.verify(_token(private_key, kid="unknown"))
    assert verifier.verify(_token(private_key))["sub"] == "user_test_owner"
    assert keys.calls == 1


def test_single_flight_background_refresh_does_not_block_cached_known_kid() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class BlockingKeys:
        block = False
        calls = 0
        started = Event()
        release = Event()

        def get_signing_keys(self, **_: object):
            self.calls += 1
            if self.block:
                self.started.set()
                assert self.release.wait(timeout=1)
            return [SimpleNamespace(key_id="test-key", key=private_key.public_key())]

    keys = BlockingKeys()
    verifier = ClerkTokenVerifier(
        _settings(), jwks_client=keys, start_background_refresh=False
    )
    assert verifier.verify(_token(private_key))["sub"] == "user_test_owner"
    keys.block = True

    with ThreadPoolExecutor(max_workers=2) as pool:
        refresh = pool.submit(verifier._refresh_signing_keys)
        assert keys.started.wait(timeout=1)
        assert verifier._refresh_signing_keys() is False
        known = pool.submit(verifier.verify, _token(private_key))
        try:
            assert known.result(timeout=0.2)["sub"] == "user_test_owner"
        finally:
            keys.release.set()
        assert refresh.result(timeout=1) is True
    assert keys.calls == 2
