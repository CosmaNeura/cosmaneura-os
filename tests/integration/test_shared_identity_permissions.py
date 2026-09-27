"""Real signatures and local rows keep shared sign-in separate from product access."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from cosmas_os.api.app import _team_recovery_scope
from cosmas_os.api.auth import AccessDenied, ClerkTokenVerifier, authenticate_request
from cosmas_os.config import Settings
from cosmas_os.models import ExternalIdentity, Principal


def test_shared_identity_requires_local_grant_and_preserves_existing_principal_scope(session, seeded):
    issuer = "https://invented.clerk.accounts.dev"
    settings = Settings(_env_file=None, cosmas_env="early_adopter_beta", data_mode="synthetic",
        auth_mode="clerk_jwt", clerk_session_policy="shared_staging", clerk_audience="",
        clerk_issuer=issuer, clerk_jwks_url=issuer + "/.well-known/jwks.json",
        clerk_organization_id="org_shared", clerk_authorized_parties="https://beta.example.invalid",
        beta_box_id=seeded["box_id"])
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    keys = SimpleNamespace(get_signing_keys=lambda **_: [SimpleNamespace(key_id="invented", key=key.public_key())])
    verifier = ClerkTokenVerifier(settings, jwks_client=keys, start_background_refresh=False)

    def authenticate(subject="user_shared", **changes):
        now = datetime.now(UTC)
        token = jwt.encode(dict(iss=issuer, sub=subject, sid="sess_shared", org_id="org_shared",
            azp="https://beta.example.invalid", iat=now, nbf=now, exp=now + timedelta(minutes=1)) | changes,
            key, algorithm="RS256", headers={"kid": "invented"})
        return authenticate_request(session, settings, authorization="Bearer " + token,
                                    box_header=None, actor_header=None, verifier=verifier)

    # Even a signed organization-admin claim cannot create product access.
    with pytest.raises(AccessDenied, match="not provisioned"):
        authenticate(org_role="org:admin")
    binding = ExternalIdentity(box_id=seeded["box_id"], principal_id=seeded["owner_id"],
        provider="clerk", issuer=issuer, subject="user_shared", organization_id="org_shared",
        reviewed_by="Invented reviewer", evidence_ref="test:explicit-shared-binding")
    session.add(binding)
    session.flush()
    original = authenticate()
    assert original.box_id == seeded["box_id"]
    assert original.principal_id == seeded["owner_id"]
    scope = _team_recovery_scope({}, original)["recovery_scope"]
    assert _team_recovery_scope({}, authenticate(sid="sess_restarted"))["recovery_scope"] == scope
    with pytest.raises(AccessDenied):
        authenticate("user_other", org_role="org:admin")
    with pytest.raises(AccessDenied):
        authenticate(org_id="org_other")
    binding.active = False
    session.flush()
    with pytest.raises(AccessDenied, match="not provisioned"):
        authenticate()
    binding.active = True
    principal = session.get(Principal, seeded["owner_id"])
    assert principal is not None
    principal.state = "disabled"
    session.flush()
    with pytest.raises(AccessDenied, match="active human"):
        authenticate()
