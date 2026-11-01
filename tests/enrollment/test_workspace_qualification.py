"""Existing signed runtime authority supplies qualification, not caller claims."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests.unit import test_practice_access as existing

from cosmas_os.api.practice_access_routes import register
from cosmas_os.application import practice_access as access

case = existing.case


def test_qualification_requires_configured_release_and_existing_human_binding(case):
    c = case
    with pytest.raises(access.PracticeAccessError):
        existing.invoke(c, access.enrollment_qualification, c.owner)
    c.config.workspace_release_source_commit = "1" * 40
    c.config.workspace_release_image_sha256 = "2" * 64
    checked, token = existing.verifier(c)
    app = FastAPI()
    register(app, runtime=lambda: c.config, verifier=lambda _origins: checked, session_factory=c.factory)
    client = TestClient(app)
    path = "/practice-access/enrollment-qualification"
    headers = {"X-Cosmas-Practice-Access-Contract": "1", "Authorization": "Bearer " + token(c.owner)}
    assert client.get(path).status_code != 200
    assert client.get(path, headers={**headers, "Authorization": "Bearer " + token(c.applicant)}).status_code == 403
    result = client.get(path, headers=headers)
    assert result.status_code == 200 and result.headers["cache-control"] == "no-store"
    proof = result.json()
    assert proof["box_id"] == c.config.beta_box_id
    assert proof["organization_id"] == c.config.clerk_organization_id
    assert proof["issuer"] == c.config.clerk_issuer
    assert proof["subject"] == c.owner.subject
    assert proof["source_commit"] == "1" * 40 and proof["image_sha256"] == "2" * 64
    assert proof["role"] == "owner"
