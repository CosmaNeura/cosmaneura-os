"""Read-only readiness uses exact owner/account scope without loading patient data."""

from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cosmas_os.api import vendor_setup_routes
from cosmas_os.api.vendor_work_schemas import public_digest
from cosmas_os.application import vendor_readiness as readiness
from cosmas_os.application import vendor_settings as setup
from cosmas_os.application.workspace import WorkspaceError
from cosmas_os.models import Principal
from cosmas_os.ports.vendor_connectors import ConnectionSelection
from cosmas_os.vendor_models import VendorConnectionVersion
from cosmas_os.vendor_setup_models import VendorSetup, VendorSetupReceipt, VendorSetupRevision


def uid(value):
    return str(UUID(int=value))


BOX, OWNER = uid(1), uid(2)
ON = setup.VendorSetupPolicy(True)


def installation(vendor, number=10, *, box=BOX, actor=OWNER, fax=True):
    capabilities = ("spruce_media_upload", "spruce_fax") if vendor == "spruce" and fax else (
        "spruce_secure_message",) if vendor == "spruce" else (vendor + "_fax",)
    return setup.Installation(
        ConnectionSelection(
            vendor=vendor, connection_id=uid(number), box_id=box, owner_id=actor,
            environment="sandbox" if vendor == "documo" else "production",
            remote_account_id=uid(number + 1) if vendor == "documo" else "123456",
            credential_ref=uid(number + 2), configuration_sha256="a" * 64,
        ), "Invented account", "Invented sender",
        {"internal_endpoint_id": "invented_endpoint"} if vendor == "spruce"
        else {"caller_id": "2125550100", **({"sender_email": "fax@example.invalid"} if vendor == "srfax" else {})}, capabilities,
    )


class AccountSession:
    """Rejects any query for a patient, recipient or remote configuration body."""

    def __init__(self, *, owner=True):
        self.info, self.rows, self.revisions, self.receipts, self.connections = {}, {}, {}, {}, {}
        self.is_owner, self.account_queries, self.rollbacks = owner, 0, 0

    def scalar(self, statement):
        entity = statement.column_descriptions[0]["entity"]
        params = statement.compile().params
        if entity is Principal:
            if params["id_1"] != OWNER or params["box_id_1"] != BOX:
                return None
            return SimpleNamespace(is_owner=self.is_owner)
        if entity is VendorSetupReceipt:
            return self.receipts[params["setup_id_1"]]
        if entity is VendorSetup:
            assert params["box_id_1"] == BOX and params["owner_id_1"] == OWNER
            return self.rows[params["id_1"]]
        raise AssertionError("Unexpected account-read entity: " + str(entity))

    def scalars(self, statement):
        assert statement.column_descriptions[0]["entity"] is VendorSetup
        params = statement.compile().params
        assert params == {"box_id_1": BOX, "owner_id_1": OWNER, "kind_1": "account", "param_1": 51}
        self.account_queries += 1
        return list(self.rows.values())

    def get(self, model, key):
        if model is VendorSetupRevision:
            return self.revisions[key]
        if model is VendorConnectionVersion:
            return self.connections[key]
        raise AssertionError("Patient or recipient lookup is forbidden")

    def expire_all(self):
        pass

    def rollback(self):
        self.rollbacks += 1

    def add_account(self, item, *, state="active", prepare=True):
        number = 100 + len(self.rows) * 10
        sid, rid, cid = uid(number), uid(number + 1), uid(number + 2)
        review = {
            "kind": "account", "setup_id": sid, "revision_id": rid, "revision": 1,
            "installed": item.public(), "label": "Invented reviewed account",
            "permissions": {"read_status": True, "prepare_and_submit": prepare,
                            "actions": list(item.capabilities)},
            "connection_version_id": cid,
        }
        digest = public_digest("cosmas-vendor-setup-review.v1", review)
        revision = SimpleNamespace(id=rid, review=review, review_sha256=digest,
                                   installation_id=str(item.selection.connection_id),
                                   installation_sha256=item.public()["installation_sha256"],
                                   connection_version_id=cid)
        row = SimpleNamespace(id=sid, box_id=BOX, owner_id=OWNER, kind="account",
                              installation_id=revision.installation_id)
        receipt = SimpleNamespace(revision_id=rid, version=1, state=state, response={"effect": {
            "setup_id": sid, "kind": "account", "version": 1, "revision_id": rid,
            "review_sha256": digest, "state": state,
        }})
        self.rows[sid], self.revisions[rid], self.receipts[sid] = row, revision, receipt
        self.connections[cid] = SimpleNamespace(is_current=state == "active", revoked_at=None,
                                                read_enabled=True, write_enabled=prepare)
        return revision


def read(session, *items, **kwargs):
    return readiness.readiness(session, BOX, OWNER, setup.Catalog(items), policy=ON, **kwargs)


def test_counts_only_scoped_fax_installations_and_returns_no_account_or_patient_content():
    session = AccountSession()
    value = read(session, installation("srfax"), installation("documo", 20, actor=uid(3)),
                 installation("spruce", 30, fax=False), installation("srfax", 40, box=uid(4)))
    assert [row["id"] for row in value["providers"]] == ["spruce", "srfax", "documo", "efax"]
    assert [row["installed_accounts"] for row in value["providers"]] == [0, 1, 0, 0]
    assert set(value) == {"contract_version", "scope", "enabled", "work_enabled",
                          "delivery_enabled", "credential_access_configured",
                          "document_storage_configured", "providers"}
    assert all(set(row) == {"id", "installed_accounts", "active_accounts", "review_required_accounts",
                            "unavailable_accounts", "prepare_enabled_accounts"}
               for row in value["providers"])
    assert not value["delivery_enabled"] and not value["credential_access_configured"]
    assert session.account_queries == 1


def test_distinguishes_pending_active_unavailable_and_missing_fax_permission():
    session = AccountSession()
    spruce, srfax, documo = installation("spruce"), installation("srfax", 20), installation("documo", 30)
    session.add_account(spruce, state="pending_review")
    session.add_account(srfax, prepare=False)
    session.add_account(documo, state="disabled")
    rows = read(session, spruce, srfax, documo)["providers"]
    assert rows[0]["review_required_accounts"] == 1 and rows[0]["active_accounts"] == 0
    assert rows[1]["active_accounts"] == 1 and rows[1]["prepare_enabled_accounts"] == 0
    assert rows[2]["unavailable_accounts"] == 1 and rows[2]["active_accounts"] == 0


def test_active_permission_drift_or_changed_installation_is_never_ready():
    session, item = AccountSession(), installation("srfax")
    revision = session.add_account(item)
    assert read(session, item)["providers"][1]["prepare_enabled_accounts"] == 1
    session.connections[revision.connection_version_id].write_enabled = False
    value = read(session, item)["providers"][1]
    assert value["active_accounts"] == 0 and value["unavailable_accounts"] == 1
    session.connections[revision.connection_version_id].write_enabled = True
    changed = replace(item, label="Changed installed account")
    value = read(session, changed)["providers"][1]
    assert value["active_accounts"] == 0 and value["unavailable_accounts"] == 1


def test_disabled_setup_retains_installation_evidence_without_claiming_active_use():
    session, item = AccountSession(), installation("srfax")
    session.add_account(item)
    value = readiness.readiness(session, BOX, OWNER, setup.Catalog((item,)))
    assert not value["enabled"]
    assert value["providers"][1]["installed_accounts"] == 1
    assert value["providers"][1]["active_accounts"] == 0


@pytest.mark.parametrize("box,actor,owner,status", [(BOX, OWNER, False, 404),
                                                   (uid(3), OWNER, True, 403),
                                                   (BOX, uid(3), True, 403)])
def test_existing_human_owner_authorization_precedes_any_account_lookup(box, actor, owner, status):
    session = AccountSession(owner=owner)
    with pytest.raises(WorkspaceError) as caught:
        readiness.readiness(session, box, actor)
    assert caught.value.status == status and session.account_queries == 0


def test_fails_closed_on_tampered_review_and_never_returns_partial_counts():
    session, item = AccountSession(), installation("srfax")
    revision = session.add_account(item)
    revision.review["label"] = "Uncommitted review"
    with pytest.raises(WorkspaceError, match="vendor_setup_integrity"):
        read(session, item)


def test_configuration_requires_booleans_and_does_not_assert_any_provider_observation():
    with pytest.raises(ValueError):
        readiness.FaxReadinessConfiguration(delivery_enabled="true")
    configured = readiness.FaxReadinessConfiguration(True, True, True, True)
    value = read(AccountSession(), configuration=configured)
    assert value["delivery_enabled"] and value["credential_access_configured"]
    assert all(row["active_accounts"] == 0 for row in value["providers"])


def test_host_reports_configuration_presence_without_fetching_credentials_or_contacting_provider(monkeypatch):
    from cosmas_os.api import app as api

    monkeypatch.setattr(api, "settings", SimpleNamespace(
        workspace_available=True, vendor_work_enabled=True, vendor_io_enabled=False,
    ))
    monkeypatch.setattr(api, "managed_services", lambda _app: SimpleNamespace(
        has_credentials=True, artifact_store=object(),
    ))
    value = api._vendor_readiness_configuration(SimpleNamespace(app=object()))
    assert value == readiness.FaxReadinessConfiguration(True, False, True, True)
    monkeypatch.setattr(api, "managed_services", lambda _app: None)
    assert api._vendor_readiness_configuration(SimpleNamespace(app=object())) == readiness.FaxReadinessConfiguration(True, False, False, False)


@pytest.mark.parametrize("owner,headers,query,status", [
    (True, {"X-Cosmas-Vendor-Setup-Contract": "1"}, "", 200),
    (False, {"X-Cosmas-Vendor-Setup-Contract": "1"}, "", 404),
    (True, {}, "", 426),
    (True, {"X-Cosmas-Vendor-Setup-Contract": "1"}, "?owner=other", 426),
])
def test_route_reuses_scoped_setup_contract_and_reauthentication(owner, headers, query, status):
    app, session, checks = FastAPI(), AccountSession(owner=owner), []
    identity = SimpleNamespace(box_id=BOX, principal_id=OWNER)
    vendor_setup_routes.register(
        app, lambda: session, lambda: identity, policy_dependency=lambda: ON,
        reauthenticate=lambda *_: checks.append("current"),
    )
    with TestClient(app) as client:
        response = client.get("/vendor-settings/readiness" + query, headers=headers)
    assert response.status_code == status
    assert response.headers["cache-control"] == "no-store"
    if status == 200:
        assert response.json()["scope"] == {"box_id": BOX, "owner_id": OWNER}
        assert len(checks) >= 2 and session.account_queries == 1
    else:
        assert session.account_queries == 0


def test_route_discards_result_if_owner_authentication_changes_before_disclosure():
    app, session, calls = FastAPI(), AccountSession(), []

    def reauthenticate(*_):
        calls.append(1)
        if len(calls) > 1:
            raise WorkspaceError("vendor_setup_unavailable", 403)

    vendor_setup_routes.register(
        app, lambda: session, lambda: SimpleNamespace(box_id=BOX, principal_id=OWNER),
        policy_dependency=lambda: ON, reauthenticate=reauthenticate,
    )
    with TestClient(app) as client:
        response = client.get("/vendor-settings/readiness", headers={"X-Cosmas-Vendor-Setup-Contract": "1"})
    assert response.status_code == 403
    assert "providers" not in response.json() and session.rollbacks == 1
