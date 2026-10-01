"""Actual PostgreSQL and closed HTTP qualification for reviewed delivery setup."""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from tests.integration.test_vendor_work import gates as gates
from tests.integration.test_vendor_work import vendor_case as vendor_case

from cosmas_os.api import app as api
from cosmas_os.api import vendor_setup_routes as routes
from cosmas_os.api import vendor_setup_schemas as p
from cosmas_os.api import vendor_work_schemas as public
from cosmas_os.application import vendor_settings as flow
from cosmas_os.application import vendor_work as work
from cosmas_os.application import workspace as ws
from cosmas_os.models import Principal
from cosmas_os.ports.vendor_connectors import ConnectionSelection
from cosmas_os.vendor_models import VendorConnectionVersion, VendorCorrespondenceVersion
from cosmas_os.vendor_setup_models import VendorSetupReceipt

ON = flow.VendorSetupPolicy(True)
OFF = flow.VendorSetupPolicy()


@pytest.fixture
def setup_case(vendor_case):
    c = vendor_case
    installations = []
    for vendor, remote, routing, capabilities in [
        (
            "spruce",
            "invented_practice",
            {"internal_endpoint_id": "invented_endpoint"},
            ["spruce_secure_message", "spruce_media_upload", "spruce_fax"],
        ),
        ("srfax", "123456", {"caller_id": "2125550199", "sender_email": "fax@example.invalid"}, ["srfax_fax"]),
        ("documo", str(uuid4()), {"caller_id": "2125550188"}, ["documo_fax"]),
    ]:
        selection = ConnectionSelection.model_validate(
            {
                "vendor": vendor,
                "connection_id": uuid4(),
                "box_id": c["box"],
                "owner_id": c["actor"],
                "environment": "sandbox" if vendor == "documo" else "production",
                "remote_account_id": remote,
                "credential_ref": uuid4(),
                "configuration_sha256": "a" * 64,
            }
        )
        installations.append(
            flow.Installation(
                selection,
                "Invented " + vendor + " account",
                "Invented sender",
                routing,
                tuple(capabilities),
            )
        )
    return {**c, "installed": flow.Catalog(installations)}


def call(s, c, method, *args, **kwargs):
    return method(s, c["box"], c["actor"], *args, **kwargs)


def account_request(c, vendor="spruce", **extra):
    profile = next(
        i.public() for i in c["installed"].installations.values() if i.selection.vendor == vendor
    )
    return p.AccountProposal.model_validate(
        {
            "setup_id": str(uuid4()),
            "expected_version": 0,
            "idempotency_key": "account-" + str(uuid4()),
            "installation_id": profile["installation_id"],
            "installation_sha256": profile["installation_sha256"],
            "label": "Invented reviewed " + vendor,
            "permissions": {
                "read_status": True,
                "prepare_and_submit": True,
                "actions": profile["capabilities"],
            },
            **extra,
        }
    )


def binding(receipt):
    x = receipt["effect"]
    return {
        "setup_id": x["setup_id"],
        "expected_version": x["version"],
        "revision_id": x["revision_id"],
        "review_sha256": x["review_sha256"],
    }


def activate(s, c, receipt, **extra):
    req = p.Activation(
        **binding(receipt),
        idempotency_key="activate-" + str(uuid4()),
        reviewed_account=True,
        reviewed_environment=True,
        reviewed_sender=True,
        reviewed_capabilities=True,
        confirm_local_activation=True,
        **extra,
    )
    return call(s, c, flow.command, "activate", req, c["installed"], policy=ON)


def account(s, c, vendor="spruce"):
    receipt = call(
        s, c, flow.propose, "propose_account", account_request(c, vendor), c["installed"], policy=ON
    )
    return activate(s, c, receipt)


def recipient_request(c, a, channel="secure", **extra):
    return p.RecipientProposal.model_validate(
        {
            "setup_id": str(uuid4()),
            "expected_version": 0,
            "idempotency_key": "recipient-" + str(uuid4()),
            "account": binding(a),
            "patient_link_id": c["correspondence"].patient_link_id,
            "destination": {"channel": "secure", "contact_id": "invented_contact"}
            if channel == "secure"
            else {"channel": "fax", "number": "+12125550123"},
            "label": "Invented reviewed recipient",
            "permission_reference": "Invented manual permission record",
            "expires_at": public.timestamp(datetime.now(UTC) + timedelta(days=2)),
            **extra,
        }
    )


def recipient(s, c, a, channel="secure"):
    req = recipient_request(c, a, channel)
    receipt = call(s, c, flow.propose, "propose_recipient", req, c["installed"], policy=ON)
    return activate(
        s, c, receipt, reviewed_patient=True, reviewed_recipient=True, reviewed_permission=True
    )


def view(s, c, receipt):
    return call(s, c, flow.detail, receipt["effect"]["setup_id"], c["installed"], policy=ON)


def command(s, c, receipt, kind, **extra):
    model = p.COMMANDS[kind]
    req = model.model_validate(
        {
            **binding(receipt),
            "idempotency_key": kind + "-" + str(uuid4()),
            "confirm_" + kind: True,
            **extra,
        }
    )
    return call(s, c, flow.command, kind, req, c["installed"], policy=ON)


@pytest.mark.parametrize(
    "vendor,channel", [("spruce", "secure"), ("spruce", "fax"), ("srfax", "fax"), ("documo", "fax")]
)
def test_reviewed_accounts_and_recipients_use_existing_c1_versions(
    session, setup_case, vendor, channel
):
    c = setup_case
    a = account(session, c, vendor)
    r = recipient(session, c, a, channel)
    ad, rd = view(session, c, a), view(session, c, r)
    assert ad["summary"]["usable_locally"] and rd["summary"]["usable_locally"]
    native = session.get(VendorConnectionVersion, ad["review"]["connection_version_id"])
    mapping = session.get(VendorCorrespondenceVersion, rd["review"]["correspondence_version_id"])
    assert native is not None and mapping is not None
    assert native.is_current and native.write_enabled and native.read_enabled and mapping.is_current
    options = work.options(session, c["box"], c["actor"], c["wid"])
    assert native.id in str(options) and mapping.id in str(options)
    if channel == "secure":
        proposal = public.VendorProposal.model_validate(
            {
                "expected_workspace_revision": 3,
                "idempotency_key": "delivery-" + str(uuid4()),
                "proposed_operation_id": str(uuid4()),
                "action": "spruce_secure_message",
                "connection": {
                    k: work._connection_view(native)[k] for k in ("id", "revision", "public_sha256")
                },
                "correspondence": {
                    k: work._correspondence_view(mapping, datetime.now(UTC))[k]
                    for k in ("id", "revision", "public_sha256")
                },
                "source": c["source"],
                "due_date": "2026-10-01",
                "expected_outcome": "Review invented delivery",
                "share_to_practice": False,
                "message": "Invented private message",
            }
        )
        admitted = work.propose(session, c["box"], c["actor"], c["wid"], proposal)
        assert admitted["summary"]["effect"] == "proposed"


def test_account_disable_invalidates_recipients_and_requires_new_review(session, setup_case):
    c = setup_case
    a = account(session, c)
    r = recipient(session, c, a)
    olda, oldr = view(session, c, a), view(session, c, r)
    disabled = command(session, c, a, "disable")
    assert not view(session, c, r)["summary"]["usable_locally"]
    with pytest.raises(ws.WorkspaceError, match="vendor_setup_revision_required"):
        activate(session, c, disabled)
    req = account_request(
        c, setup_id=a["effect"]["setup_id"], expected_version=disabled["effect"]["version"]
    )
    new = activate(
        session,
        c,
        call(session, c, flow.propose, "propose_account", req, c["installed"], policy=ON),
    )
    assert (
        view(session, c, new)["review"]["connection_version_id"]
        != olda["review"]["connection_version_id"]
    )
    assert not view(session, c, r)["summary"]["usable_locally"]
    assert (
        session.get(
            VendorCorrespondenceVersion, oldr["review"]["correspondence_version_id"]
        ).is_current
        is False
    )


def test_recipient_revisions_preserve_history_and_old_binding_stays_retired(session, setup_case):
    c = setup_case
    a = account(session, c)
    r = recipient(session, c, a)
    d = view(session, c, r)
    req = recipient_request(
        c,
        a,
        setup_id=r["effect"]["setup_id"],
        expected_version=r["effect"]["version"],
        destination={"channel": "secure", "contact_id": "different_invented_contact"},
    )
    new = call(session, c, flow.propose, "propose_recipient", req, c["installed"], policy=ON)
    assert (
        session.get(
            VendorCorrespondenceVersion, d["review"]["correspondence_version_id"]
        ).is_current
        is False
    )
    assert view(session, c, new)["summary"]["state"] == "pending_review"
    history = call(session, c, flow.history, new["effect"]["setup_id"])
    assert len(history["items"]) == 3 and len(history["reviews"]) == 2
    assert history["reviews"][0]["destination"]["contact_id"] == "invented_contact"


def test_exact_recovery_survives_disabled_flag_and_changed_installation(session, setup_case):
    c = setup_case
    req = account_request(c)
    first = call(session, c, flow.propose, "propose_account", req, c["installed"], policy=ON)
    assert (
        call(session, c, flow.propose, "propose_account", req, flow.EMPTY_CATALOG, policy=OFF)
        == first
    )
    resolved = call(
        session,
        c,
        flow.resolve,
        p.Resolve(
            command_kind="propose_account",
            idempotency_key=req.idempotency_key,
            request_sha256=first["request_sha256"],
        ),
    )
    assert resolved == first
    with pytest.raises(ws.WorkspaceError, match="vendor_setup_idempotency_conflict"):
        altered = p.AccountProposal.model_validate(req.public() | {"label": "Altered"})
        call(session, c, flow.propose, "propose_account", altered, c["installed"], policy=ON)
    with pytest.raises(ws.WorkspaceError, match="vendor_setup_disabled"):
        call(
            session,
            c,
            flow.propose,
            "propose_account",
            account_request(c),
            c["installed"],
            policy=OFF,
        )


@pytest.mark.parametrize("case", ["staff", "other_owner", "revoked_owner"])
def test_current_owner_scope_denies_private_setup_and_recovery(session, setup_case, case):
    c = setup_case
    a = account(session, c)
    if case == "revoked_owner":
        actor = c["actor"]
        row = session.get(Principal, actor)
        row.state = "disabled"
    else:
        row = Principal(
            box_id=c["box"],
            principal_type="human",
            display_name="Invented " + case,
            is_owner=case == "other_owner",
            state="active",
        )
        session.add(row)
        session.flush()
        actor = row.id
    session.commit()
    with pytest.raises(ws.WorkspaceError):
        flow.detail(session, c["box"], actor, a["effect"]["setup_id"], c["installed"], policy=ON)
    if case != "other_owner":
        with pytest.raises(ws.WorkspaceError):
            flow.catalog(session, c["box"], actor, c["installed"], policy=ON)
    else:
        assert flow.catalog(session, c["box"], actor, c["installed"], policy=ON)["setups"] == []


@pytest.mark.parametrize(
    "change",
    [
        {"destination": {"channel": "fax", "number": "https://evil.invalid"}},
        {"destination": {"channel": "email", "address": "a@example.invalid"}},
        {"credential_ref": str(uuid4())},
        {"endpoint": "https://evil.invalid"},
    ],
)
def test_closed_recipient_inputs_reject_other_channels_and_credentials(session, setup_case, change):
    c = setup_case
    a = account(session, c)
    with pytest.raises(ValueError):
        recipient_request(c, a, **change)


@pytest.mark.parametrize("delta", [-1, 31])
def test_permission_requires_future_bounded_expiry(session, setup_case, delta):
    c = setup_case
    a = account(session, c)
    req = recipient_request(
        c, a, expires_at=public.timestamp(datetime.now(UTC) + timedelta(days=delta))
    )
    with pytest.raises(ws.WorkspaceError, match="vendor_permission_expired"):
        call(session, c, flow.propose, "propose_recipient", req, c["installed"], policy=ON)
    assert (
        session.scalar(
            select(func.count())
            .select_from(VendorSetupReceipt)
            .where(VendorSetupReceipt.setup_id == a["effect"]["setup_id"])
        )
        == 2
    )


@pytest.fixture
def client(session, setup_case):
    app = FastAPI()
    app.dependency_overrides[api.get_session] = lambda: session
    routes.register(
        app,
        api.get_session,
        api._identity,
        policy_dependency=lambda: ON,
        catalog_dependency=lambda: setup_case["installed"],
    )
    with TestClient(app) as value:
        yield value


def test_actual_http_contract_exact_history_and_private_catalog(
    client, session, setup_case, tmp_path
):
    c = setup_case
    h = {
        "X-Box-Id": c["box"],
        "X-Actor-Principal-Id": c["actor"],
        "X-Cosmas-Vendor-Setup-Contract": "1",
    }
    catalog = client.get("/vendor-settings", headers=h)
    assert catalog.status_code == 200, catalog.text
    request = account_request(c)
    first = client.post("/vendor-settings/propose_account", headers=h, json=request.public())
    assert first.status_code == 200, first.text
    saved = first.json()
    path = "/vendor-settings/" + saved["effect"]["setup_id"]
    assert (
        client.post("/vendor-settings/propose_account", headers=h, json=request.public()).json()
        == saved
    )
    d = client.get(path, headers=h).json()
    history = client.get(path + "/history", headers=h).json()
    p.Detail.model_validate(d)
    p.History.model_validate(history)
    wire = json.dumps([catalog.json(), d, history])
    assert "credential_ref" not in wire and "internal_endpoint_id" not in wire
    assert client.get("/vendor-settings").status_code in {401, 422}
    assert client.get("/vendor-settings?unexpected=1", headers=h).status_code == 426
    assert (
        client.get(
            "/vendor-settings", headers={**h, "X-Cosmas-Vendor-Setup-Contract": "2"}
        ).status_code
        == 426
    )
    (tmp_path / "actual-vendor-settings-http.json").write_text(
        json.dumps(
            {
                "catalog": catalog.json(),
                "account_request": request.public(),
                "account_receipt": saved,
                "detail": d,
                "history": history,
            },
            indent=2,
        )
    )
