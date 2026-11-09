"""Shared EhrConnector interface: fail-closed writes and production targets."""

from __future__ import annotations

import pytest

from cosmas_os.plugins.ehr import (
    CapabilityManifest,
    DeclaredEhrConnector,
    EhrConnector,
    EhrReadRefused,
    EhrTargetRefused,
    EhrWriteRefused,
)
from cosmas_os.plugins.ehr.connector import READ_ACTIONS, WRITE_ACTIONS
from cosmas_os.plugins.ehr.refusals import (
    PRACTICE_SCOPE_REFUSED_MESSAGE,
    PRACTICE_SCOPE_REQUIRED_MESSAGE,
    PRODUCTION_TARGET_MESSAGE,
    RESOURCE_UNSUPPORTED_MESSAGE,
    WRITE_REFUSED_MESSAGE,
)
from cosmas_os.plugins.ehr.registry import build_default_registry

VENDORS = ("athena", "atlas_md", "elation", "tebra")
NON_STRING_RESOURCES = (
    [],
    {},
    b"appointments",
    None,
    1,
    1.5,
    True,
)

BETA_MUTATION_GAPS = (
    "DELETE",
    "Write",
    "patch",
    "post",
    "put",
    "upsert",
    "modify",
    "amend",
    "sign_order",
)


def _manifest(**overrides) -> CapabilityManifest:
    values = dict(
        vendor_id="elation",
        display_name="Elation",
        auth_styles=frozenset({"cosmas_session", "oauth2_client_credentials"}),
        readable_resources=frozenset({"appointments", "medications"}),
        unsupported_actions=frozenset({"write_chart", "prescribe", "production_target"}),
        sandbox_supported=True,
        production_supported=False,
        writes_supported=False,
    )
    values.update(overrides)
    return CapabilityManifest(**values)


def test_declared_connector_satisfies_protocol():
    connector = DeclaredEhrConnector(_manifest())
    assert isinstance(connector, EhrConnector)
    assert connector.vendor_id == "elation"
    assert connector.capability_manifest().display_name == "Elation"


@pytest.mark.parametrize("action", sorted(WRITE_ACTIONS))
def test_refuse_write_always_raises_for_known_mutations(action):
    connector = DeclaredEhrConnector(_manifest())
    with pytest.raises(EhrWriteRefused) as raised:
        connector.assert_not_write_action(action)
    assert raised.value.code == "ehr_write_refused"
    with pytest.raises(EhrWriteRefused):
        connector.refuse_write(action)


def test_write_refusal_has_code_and_plain_english_message():
    connector = DeclaredEhrConnector(_manifest())
    with pytest.raises(EhrWriteRefused) as raised:
        connector.assert_not_write_action("DELETE")
    assert raised.value.code == "ehr_write_refused"
    assert raised.value.message
    assert raised.value.message == WRITE_REFUSED_MESSAGE
    assert raised.value.message == "CosmaBot can only read from EHRs; it can't change records."


@pytest.mark.parametrize("action", BETA_MUTATION_GAPS)
def test_assert_not_write_action_refuses_beta_mutation_gaps(action):
    connector = DeclaredEhrConnector(_manifest())
    with pytest.raises(EhrWriteRefused) as raised:
        connector.assert_not_write_action(action)
    assert raised.value.code == "ehr_write_refused"


@pytest.mark.parametrize("action", [
    " DELETE ",
    "\tWrite\n",
    "  patch  ",
    "POST",
    "Put",
    " UPSERT ",
    "Modify",
    "AMEND",
    " Sign_Order ",
    "write_custom_mutation",
    "unknown_action",
    "",
    "   ",
])
def test_assert_not_write_action_refuses_case_and_whitespace_variants(action):
    connector = DeclaredEhrConnector(_manifest())
    with pytest.raises(EhrWriteRefused) as raised:
        connector.assert_not_write_action(action)
    assert raised.value.code == "ehr_write_refused"


@pytest.mark.parametrize("action", sorted(READ_ACTIONS))
def test_assert_not_write_action_allows_explicit_read_actions(action):
    connector = DeclaredEhrConnector(_manifest())
    connector.assert_not_write_action(action)
    connector.assert_not_write_action(f"  {action.upper()}  ")


def test_default_registry_refuses_beta_mutation_gaps_on_elation():
    connector = build_default_registry().require("elation")
    for action in BETA_MUTATION_GAPS:
        with pytest.raises(EhrWriteRefused):
            connector.assert_not_write_action(action)


def test_writes_supported_cannot_be_true_on_manifest():
    with pytest.raises(ValueError, match="writes_not_part_of_this_contract"):
        _manifest(writes_supported=True)


def test_sandbox_allowed_when_declared():
    connector = DeclaredEhrConnector(_manifest(sandbox_supported=True))
    connector.allow_target("sandbox")
    connector.allow_read("appointments", target="sandbox")


def test_sandbox_refused_when_not_declared():
    connector = DeclaredEhrConnector(
        _manifest(sandbox_supported=False, readable_resources=frozenset())
    )
    with pytest.raises(EhrTargetRefused) as raised:
        connector.allow_target("sandbox")
    assert raised.value.code == "ehr_target_refused"
    assert raised.value.target == "sandbox"
    assert raised.value.message == "That EHR target is not allowed."


def test_production_refused_by_default_even_with_claim():
    connector = DeclaredEhrConnector(_manifest(production_supported=True))
    with pytest.raises(EhrTargetRefused) as raised:
        connector.allow_target("production")
    assert raised.value.code == "ehr_target_refused"
    assert raised.value.target == "production"
    assert raised.value.message == PRODUCTION_TARGET_MESSAGE
    assert raised.value.message == "CosmaBot can only connect to sandbox EHRs right now."


def test_production_refused_when_manifest_disallows_even_if_gate_allows():
    class AllowAll:
        def allow_production(self, *, vendor_id, target):
            return True

    connector = DeclaredEhrConnector(_manifest(production_supported=False))
    with pytest.raises(EhrTargetRefused) as raised:
        connector.allow_target("production", production_gate=AllowAll())
    assert raised.value.code == "ehr_target_refused"
    assert raised.value.message == PRODUCTION_TARGET_MESSAGE


def test_production_allowed_only_with_manifest_claim_and_c14_gate():
    class AllowAll:
        def allow_production(self, *, vendor_id, target):
            assert vendor_id == "elation"
            assert target == "production"
            return True

    connector = DeclaredEhrConnector(_manifest(production_supported=True))
    connector.allow_target("production", production_gate=AllowAll())


def test_production_still_refused_when_c14_gate_denies():
    class DenyAll:
        def allow_production(self, *, vendor_id, target):
            return False

    connector = DeclaredEhrConnector(_manifest(production_supported=True))
    with pytest.raises(EhrTargetRefused) as raised:
        connector.allow_target("production", production_gate=DenyAll())
    assert raised.value.code == "ehr_target_refused"
    assert raised.value.message == PRODUCTION_TARGET_MESSAGE


def test_allow_read_refuses_undeclared_resource():
    connector = DeclaredEhrConnector(_manifest())
    with pytest.raises(EhrReadRefused) as raised:
        connector.allow_read("allergies", target="sandbox")
    assert raised.value.code == "ehr_resource_unsupported"
    assert raised.value.message == RESOURCE_UNSUPPORTED_MESSAGE
    assert raised.value.message == (
        "That EHR resource isn't available for this connection."
    )


def test_allow_read_refuses_production_by_default():
    connector = DeclaredEhrConnector(_manifest())
    with pytest.raises(EhrTargetRefused) as raised:
        connector.allow_read("appointments", target="production")
    assert raised.value.code == "ehr_target_refused"
    assert raised.value.message == PRODUCTION_TARGET_MESSAGE


@pytest.mark.parametrize("vendor_id", VENDORS)
def test_allow_read_refusals_carry_plain_english_message_for_each_vendor(vendor_id):
    connector = build_default_registry().require(vendor_id)
    if vendor_id == "atlas_md":
        with pytest.raises(EhrTargetRefused) as raised:
            connector.allow_read("appointments", target="sandbox")
        assert raised.value.code == "ehr_target_refused"
        assert raised.value.message == "That EHR target is not allowed."
        return

    undeclared = {
        "athena": "problems",
        # Elation FHIR adapter declares allergies; visit_link_status stays undeclared.
        "elation": "visit_link_status",
        "tebra": "labs",
    }[vendor_id]
    with pytest.raises(EhrReadRefused) as raised:
        connector.allow_read(undeclared, target="sandbox")
    assert raised.value.code == "ehr_resource_unsupported"
    assert raised.value.message == RESOURCE_UNSUPPORTED_MESSAGE


@pytest.mark.parametrize("vendor_id", VENDORS)
@pytest.mark.parametrize("resource", NON_STRING_RESOURCES)
def test_allow_read_non_string_resource_raises_contract_refusal(vendor_id, resource):
    connector = build_default_registry().require(vendor_id)
    with pytest.raises(EhrReadRefused) as raised:
        connector.allow_read(resource, target="sandbox")  # type: ignore[arg-type]
    assert raised.value.code == "ehr_resource_unsupported"
    assert raised.value.message == RESOURCE_UNSUPPORTED_MESSAGE
    assert "TypeError" not in type(raised.value).__name__
    # Never echo the caller's input in the plain message.
    assert repr(resource) not in raised.value.message
    assert str(resource) not in raised.value.message


def test_c6_practice_scope_hook_can_refuse():
    class Scope:
        def allow_practice(self, *, vendor_id, practice_ref, resource):
            return practice_ref == "practice-ok"

    connector = DeclaredEhrConnector(_manifest())
    with pytest.raises(EhrReadRefused) as raised:
        connector.allow_read(
            "appointments",
            target="sandbox",
            practice_ref="practice-other",
            practice_scope=Scope(),
        )
    assert raised.value.code == "ehr_practice_scope_refused"
    assert raised.value.message == PRACTICE_SCOPE_REFUSED_MESSAGE
    connector.allow_read(
        "appointments",
        target="sandbox",
        practice_ref="practice-ok",
        practice_scope=Scope(),
    )


def test_c6_practice_scope_requires_practice_ref():
    class Scope:
        def allow_practice(self, *, vendor_id, practice_ref, resource):
            return True

    connector = DeclaredEhrConnector(_manifest())
    with pytest.raises(EhrReadRefused) as raised:
        connector.allow_read("appointments", practice_scope=Scope())
    assert raised.value.code == "ehr_practice_scope_required"
    assert raised.value.message == PRACTICE_SCOPE_REQUIRED_MESSAGE


def test_c6_read_audit_hook_records_allowed_and_refused():
    events: list[tuple[str, str]] = []

    class Audit:
        def record_read(self, *, vendor_id, resource, target, practice_ref, outcome):
            events.append((resource, outcome))

    connector = DeclaredEhrConnector(_manifest())
    connector.allow_read("appointments", read_audit=Audit())
    with pytest.raises(EhrReadRefused):
        connector.allow_read("labs", read_audit=Audit())
    assert events == [("appointments", "allowed"), ("labs", "refused")]


def test_hook_slots_default_to_none_for_c2_c3_c4():
    connector = DeclaredEhrConnector(_manifest())
    assert connector.auth_provider is None
    assert connector.secret_resolver is None
    assert connector.fhir_read_client is None


def test_unknown_target_refused():
    connector = DeclaredEhrConnector(_manifest())
    with pytest.raises(EhrTargetRefused) as raised:
        connector.allow_target("staging")  # type: ignore[arg-type]
    assert raised.value.code == "ehr_target_refused"
    assert raised.value.message == "That EHR target is not allowed."
