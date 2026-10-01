"""eFax keeps the existing approval, PDF, recipient and immutable account boundaries."""

import importlib.util
import json
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.unit.test_vendor_connector_foundation import NOW, PDF, approval, command, uid
from tests.unit.test_vendor_readiness import AccountSession, installation, read
from tests.unit.test_vendor_work_contract import fixture

from cosmas_os.api import vendor_setup_schemas as setup
from cosmas_os.api import vendor_work_schemas as public
from cosmas_os.application import vendor_execution as execution
from cosmas_os.application import vendor_settings
from cosmas_os.ports import vendor_connectors as private

ROOT = Path(__file__).parents[2]


def test_efax_is_only_a_reviewed_production_fax_capability():
    item = installation("efax")
    assert setup.InstalledAccount.model_validate(item.public()).vendor == "efax"
    for patch in ({"environment": "sandbox"}, {"capabilities": ["spruce_secure_message"]}):
        with pytest.raises(ValueError):
            setup.InstalledAccount.model_validate(item.public() | patch)
    config = fixture("connection") | {"vendor": "efax", "environment": "production", "actions": ["efax_fax"]}
    assert public.ConnectionView.model_validate(config).actions == ["efax_fax"]
    with pytest.raises(ValueError):
        public.ConnectionView.model_validate(config | {"actions": ["documo_fax"]})


def test_efax_proposal_requires_exact_pdf_and_reviewed_recipient_without_message_or_upload_reference():
    base = fixture("proposal")
    base.pop("message", None)
    base.pop("uploaded_media_operation_id", None)
    document = private.DocumentBinding(artifact_id=uid(5), sha256="a" * 64, byte_length=8)
    value = base | {"action": "efax_fax", "document": document.model_dump(mode="json", exclude={"display_name"})}
    assert public.VendorProposal.model_validate(value).action == "efax_fax"
    for field in ("document", "correspondence"):
        missing = value.copy()
        missing.pop(field)
        with pytest.raises(ValueError):
            public.VendorProposal.model_validate(missing)
    for extra in ({"message": "Unreviewed body"}, {"uploaded_media_operation_id": str(uid(8))}):
        with pytest.raises(ValueError):
            public.VendorProposal.model_validate(value | extra)


def test_efax_reference_is_the_documented_fax_uuid_and_stays_bound_to_exact_account():
    cmd = command("efax")
    ref = private.ProviderReference(
        vendor="efax", connection_id=cmd.selection.connection_id, environment="production",
        selection_sha256=cmd.selection.commitment(), operation_id=cmd.operation_id,
        request_sha256=cmd.commitment(), kind="fax", value=str(uid(10)), observed_at=NOW,
    )
    assert ref.value == str(uid(10))
    for bad in ("123456", "../faxes/1", str(uid(10)) + "\n"):
        with pytest.raises(ValueError):
            private.ProviderReference.model_validate(ref.model_dump(mode="python") | {"value": bad})
    with pytest.raises(ValueError):
        private.ProviderReference.model_validate(ref.model_dump(mode="python") | {"kind": "conversation_item"})
    assert approval(cmd).selection_sha256 == cmd.selection.commitment()


def test_efax_readiness_is_a_fourth_option_and_requires_current_review_and_permission():
    session, item = AccountSession(), installation("efax")
    value = read(session, item)
    assert value["providers"][3]["id"] == "efax"
    assert value["providers"][3]["installed_accounts"] == 1
    assert value["providers"][3]["prepare_enabled_accounts"] == 0
    session.add_account(item)
    assert read(session, item)["providers"][3]["prepare_enabled_accounts"] == 1


def test_efax_installation_cannot_configure_unimplemented_inbound_or_sender_email_routes():
    item = installation("efax")
    for extra in ({"event_route_id": str(uid(90))}, {"sender_email": "invented@example.invalid"}):
        with pytest.raises(ValueError, match="Closed installed routing required"):
            vendor_settings.Catalog((replace(item, routing=dict(item.routing) | extra),))


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["submit", "read"])
async def test_existing_execution_dispatch_passes_exact_efax_command_and_approval(mode, monkeypatch):
    cmd, calls, settled = command("efax"), [], []
    sentinel = object()
    invocation = SimpleNamespace(mode=mode, command=cmd, approval=approval(cmd), reference=object(),
                                 box_id=str(cmd.selection.box_id), workspace_id=str(uid(40)),
                                 owner_id=str(cmd.selection.owner_id))

    class Connector:
        def __init__(self, runtime):
            assert runtime.selection == cmd.selection

        async def submit(self, supplied, binding, document):
            calls.append((supplied, binding, document))
            return sentinel

        async def observe(self, supplied, reference):
            calls.append((supplied, reference))
            return sentinel

    monkeypatch.setattr(execution, "EFaxConnector", Connector)
    runtime = execution.VendorExecution(lambda: None, lambda _: None,
                                       artifact_store=SimpleNamespace(read_verified=lambda *_args, **_kwargs: PDF))
    monkeypatch.setattr(runtime, "_mark", lambda _invocation: True)
    monkeypatch.setattr(runtime, "_settle", lambda *args: settled.append(args))
    await runtime._invoke(invocation, time.monotonic() + 30)
    expected = [(cmd, invocation.approval, PDF)] if mode == "submit" else [(cmd, invocation.reference)]
    assert calls == expected
    assert settled == [(invocation, sentinel, None)]


def test_generated_browser_contracts_are_reproducible_from_public_python_models():
    path = ROOT / "scripts/generate-vendor-contracts.py"
    spec = importlib.util.spec_from_file_location("generate_vendor_contracts", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name, modules, prefix, contract, sort in (
        ("vendor-schema.ts", (module.work, module.retirement), "VENDOR", "vendor-contract", False),
        ("vendor-setup-schema.ts", (module.setup,), "VENDOR_SETUP", "vendor-setup-contract", True),
    ):
        assert (ROOT / "web/src" / name).read_text() == module.render(modules, prefix, contract, sort=sort)


def test_additive_migration_preserves_all_other_setup_revision_guards():
    path = ROOT / "migrations/versions/d91e7a3c5b20_reviewed_efax_delivery.py"
    spec = importlib.util.spec_from_file_location("efax_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    previous = (ROOT / "migrations/versions/4c72a86d1e90_reviewed_delivery_settings.py").read_text()
    start = previous.index("CREATE FUNCTION public.vendor_settings_revision_guard()")
    previous = previous[start:previous.index("CREATE TRIGGER vendor_settings_revision_admission", start)]
    restored = migration.GUARD_DDL.strip().replace("CREATE OR REPLACE FUNCTION", "CREATE FUNCTION", 1)
    restored = restored.replace("c.vendor NOT IN ('spruce','srfax','documo','efax')", "c.vendor NOT IN ('spruce','srfax','documo')")
    restored = restored.replace("WHEN 'documo' THEN '[\"documo_fax\"]'::jsonb WHEN 'efax' THEN '[\"efax_fax\"]'::jsonb ELSE '[]'::jsonb END", "ELSE '[\"documo_fax\"]'::jsonb END")
    assert restored == previous.strip()
    assert "vendor_event" not in migration.CHECK_DDL
    assert json.loads((ROOT / "infra/beta/environment/release-schema.json").read_text())["schema_revision"] == migration.revision
    with pytest.raises(RuntimeError, match="Retained eFax work"):
        migration.downgrade()
