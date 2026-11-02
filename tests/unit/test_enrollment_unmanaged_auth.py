"""Unmanaged authentication never needs enrollment history or session metadata."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast
from unittest.mock import Mock

import pytest
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from cosmas_os.adapters.enrollment_admission import EnrollmentAdmissionAdapter
from cosmas_os.api.auth import AccessDenied, AuthenticationFailed, authenticate_request
from cosmas_os.config import Settings
from cosmas_os.models import ExternalIdentity

SUBJECT = "user_invented_unmanaged_unbound"
TOKEN = "invented-unmanaged-bearer"


@pytest.fixture
def unmanaged_runtime() -> Settings:
    values: dict[str, Any] = json.loads((Path(__file__).parents[1] / "fixtures/hosted-workspace-settings.json").read_text())
    values["_env_file"] = None
    runtime = Settings(**values)
    assert runtime.workspace_enrollment_managed is False
    runtime.validate_runtime_configuration()
    return runtime


class VerifiedSubject:
    def __init__(self, runtime: Settings) -> None:
        self.runtime = runtime
        self.calls: list[str] = []

    def verify(self, token: str) -> dict[str, Any]:
        assert token == TOKEN
        self.calls.append(token)
        return {"sub": SUBJECT, "org_id": self.runtime.clerk_organization_id}


class NoEnrollmentSession:
    """A bounded double records metadata separately from the one binding read."""

    def __init__(self, *, allow_binding_read: bool = False) -> None:
        self.allow_binding_read = allow_binding_read
        self.metadata_reads = 0
        self.statements: list[Select[Any]] = []

    @property
    def info(self) -> dict[str, Any]:
        self.metadata_reads += 1
        if not self.allow_binding_read:
            raise AssertionError("Unmanaged rejection must not access session metadata")
        return {}

    def scalar(self, statement: Select[Any]) -> None:
        self.statements.append(statement)
        if not self.allow_binding_read:
            raise AssertionError("Authentication rejection must precede database access")
        assert len(self.statements) == 1, "Unmanaged identity denial must not read enrollment history"
        assert statement.column_descriptions[0]["entity"] is ExternalIdentity
        return None


def test_unmanaged_missing_bearer_rejects_without_session_metadata_or_database(unmanaged_runtime: Settings) -> None:
    session = NoEnrollmentSession()
    verifier = VerifiedSubject(unmanaged_runtime)
    adapter = Mock(spec=EnrollmentAdmissionAdapter)
    with pytest.raises(AuthenticationFailed, match="bearer token required"):
        authenticate_request(cast(Session, session), unmanaged_runtime,
            authorization=None, box_header=None, actor_header=None, verifier=verifier,
            admission_adapter=cast(EnrollmentAdmissionAdapter, adapter))
    assert session.metadata_reads == 0 and session.statements == []
    assert verifier.calls == []
    adapter.authorize.assert_not_called()


@pytest.mark.parametrize("box_header,actor_header", [
    ("00000000-0000-4000-8000-000000000001", None),
    (None, "00000000-0000-4000-8000-000000000002"),
])
def test_unmanaged_caller_identity_headers_reject_without_session_metadata_or_database(
    unmanaged_runtime: Settings, box_header: str | None, actor_header: str | None,
) -> None:
    session = NoEnrollmentSession()
    verifier = VerifiedSubject(unmanaged_runtime)
    adapter = Mock(spec=EnrollmentAdmissionAdapter)
    with pytest.raises(AuthenticationFailed, match="caller-supplied identity headers are not accepted"):
        authenticate_request(cast(Session, session), unmanaged_runtime,
            authorization="Bearer " + TOKEN, box_header=box_header, actor_header=actor_header,
            verifier=verifier, admission_adapter=cast(EnrollmentAdmissionAdapter, adapter))
    assert session.metadata_reads == 0 and session.statements == []
    assert verifier.calls == []
    adapter.authorize.assert_not_called()


def test_unmanaged_unbound_subject_uses_only_original_binding_lookup(unmanaged_runtime: Settings) -> None:
    session = NoEnrollmentSession(allow_binding_read=True)
    verifier = VerifiedSubject(unmanaged_runtime)
    adapter = Mock(spec=EnrollmentAdmissionAdapter)
    with pytest.raises(AccessDenied, match="identity is not provisioned"):
        authenticate_request(cast(Session, session), unmanaged_runtime,
            authorization="Bearer " + TOKEN, box_header=None, actor_header=None, verifier=verifier,
            admission_adapter=cast(EnrollmentAdmissionAdapter, adapter))
    assert session.metadata_reads == 0 and len(session.statements) == 1
    expected = select(ExternalIdentity).where(
        ExternalIdentity.provider == "clerk", ExternalIdentity.issuer == unmanaged_runtime.clerk_issuer,
        ExternalIdentity.subject == SUBJECT, ExternalIdentity.organization_id == unmanaged_runtime.clerk_organization_id,
        ExternalIdentity.active.is_(True))
    clause = session.statements[0].whereclause
    assert clause is not None and expected.whereclause is not None
    assert clause.compare(expected.whereclause)
    assert verifier.calls == [TOKEN]
    adapter.authorize.assert_not_called()
