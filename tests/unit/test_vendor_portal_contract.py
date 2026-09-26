"""An explicitly invented in-memory portal contract; no vendor mapping or I/O."""

import hashlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
from pydantic import ValidationError

from cosmas_os.adapters.vendor_connectors.portals import (
    PRODUCTION_PORTALS,
    PortalBinding,
    PortalImplementation,
    PortalProfile,
    PortalRegistry,
    PortalRoute,
    PortalRouteBindings,
)
from cosmas_os.adapters.vendor_connectors.transport import checked, require_reference
from cosmas_os.ports.vendor_connectors import (
    ApprovalBinding,
    CapabilityDescription,
    ConnectionSelection,
    DocumentBinding,
    PortalAttachment,
    PortalCorrespondence,
    PortalDocumentIntent,
    PortalObservation,
    PortalReferralIntent,
    PreparedPortalRequest,
    ProviderReference,
    SubmissionObservation,
    VendorCommand,
    VendorError,
)

NOW = datetime(2026, 9, 21, 15, tzinfo=UTC)
PDF = b"%PDF-1.7\n% invented in-memory contract byte fixture only\n%%EOF"


def uid(n):
    return UUID(f"00000000-0000-4000-8000-{n:012d}")


def route(capability):
    reading = capability == "referral.read"
    upload = capability == "document.upload"
    return PortalRoute(capability=capability, origin_index=0, method="GET" if reading else "POST",
        path_template="/synthetic/referrals/{reference}" if reading else "/synthetic/patients/{patient_id}/documents" if upload else "/synthetic/referrals",
        idempotency="read_only" if reading else "not_documented", reconciliation="not_applicable" if reading else "manual_review_only" if upload else "exact_reference_read",
        request_contract_sha256="a" * 64, response_contract_sha256="b" * 64)


def profile():
    capabilities = ("document.upload", "referral.submit", "referral.read")
    return PortalProfile(portal_id="synthetic_only", contract_version="1", documentation_sha256="c" * 64,
        origins=("https://portal.example.invalid",), capabilities=tuple(CapabilityDescription(capability=kind, evidence="documented") for kind in capabilities),
        auth_scheme="oauth2_bearer", correspondence=("patient", "practice", "recipient"), receipt_parser_version="synthetic-v1",
        routes=tuple(route(kind) for kind in capabilities))


def selection():
    return ConnectionSelection(vendor="portal", connection_id=uid(1), box_id=uid(2), owner_id=uid(3), environment="sandbox",
        remote_account_id="synthetic_practice", credential_ref=uid(4), configuration_sha256="d" * 64)


def document():
    return DocumentBinding(artifact_id=uid(5), sha256=hashlib.sha256(PDF).hexdigest(), byte_length=len(PDF))


def correspondence():
    return PortalCorrespondence(patient_mapping_id=uid(6), practice_mapping_id=uid(7), recipient_mapping_id=uid(8), mappings_sha256="e" * 64)


def upload_command(selected_profile):
    return VendorCommand(selection=selection(), operation_id=uid(9), revision_id=uid(10), expires_at=NOW + timedelta(minutes=2),
        intent=PortalDocumentIntent(portal_id=selected_profile.portal_id, profile_sha256=selected_profile.commitment(), correspondence=correspondence(), document=document()))


def approve(command):
    return ApprovalBinding(operation_id=command.operation_id, revision_id=command.revision_id, action=command.intent.kind,
        approved_payload_sha256=command.commitment(), selection_sha256=command.selection.commitment(), expires_at=command.expires_at)


class SyntheticInMemoryPortal:
    """Test implementation only. No actual portal effect, credential or delivery."""

    def __init__(self):
        self.profile = profile()
        self.enabled = False
        self.current_authority = False
        self.effects = []

    def prepare(self, command: VendorCommand, document: bytes | None = None) -> PreparedPortalRequest:
        return PreparedPortalRequest(command=checked(command), profile_sha256=self.profile.commitment(), document=document)

    async def submit(self, prepared: PreparedPortalRequest, approval: ApprovalBinding) -> SubmissionObservation:
        if not self.enabled:
            raise VendorError("connector_disabled")
        if not self.current_authority:
            raise VendorError("authority_required")
        prepared = PreparedPortalRequest.model_validate(prepared.model_dump(mode="python"))
        command = prepared.command
        approval.require_command(command, NOW)
        if prepared.profile_sha256 != self.profile.commitment():
            raise VendorError("connection_changed")
        upload = isinstance(command.intent, PortalDocumentIntent)
        ref = ProviderReference(vendor="portal", connection_id=command.selection.connection_id, environment=command.selection.environment,
            selection_sha256=command.selection.commitment(), operation_id=command.operation_id, request_sha256=command.commitment(),
            kind="portal_document" if upload else "portal_referral", value="syntheticDocument_1" if upload else "syntheticReferral_1", observed_at=NOW,
            artifact_sha256=command.intent.document.sha256 if upload else None, portal_id=command.intent.portal_id,
            portal_profile_sha256=command.intent.profile_sha256, correspondence_sha256=command.intent.correspondence.commitment())
        self.effects.append(command.commitment())
        return SubmissionObservation(vendor="portal", connection_id=command.selection.connection_id, operation_id=command.operation_id,
            request_sha256=command.commitment(), observed_at=NOW, state="accepted", reference=ref, safe_error=None, response_sha256="f" * 64)

    async def observe(self, command: VendorCommand, reference: ProviderReference) -> PortalObservation:
        if not self.enabled:
            raise VendorError("connector_disabled")
        if not self.current_authority:
            raise VendorError("authority_required")
        reference = require_reference(checked(command), reference, "portal_referral")
        return PortalObservation(reference=reference, observed_at=NOW, state="pending", response_sha256="f" * 64)


@pytest.mark.asyncio
async def test_typed_in_memory_upload_referral_observe_with_separate_authority_and_no_network(monkeypatch):
    async def no_http(*_args, **_kwargs):
        raise AssertionError("The synthetic portal must perform zero HTTP calls")

    monkeypatch.setattr(httpx.AsyncClient, "send", no_http)
    implementation = SyntheticInMemoryPortal()
    adapter: PortalImplementation = implementation
    registry = PortalRegistry((PortalBinding(adapter.profile, adapter),))
    command = upload_command(adapter.profile)
    prepared = registry.prepare(command, PDF)
    assert "invented" not in prepared.model_dump_json() and prepared.document.get_secret_value() == PDF
    with pytest.raises(VendorError, match="connector_disabled"):
        await adapter.submit(prepared, approve(command))
    implementation.enabled = True
    with pytest.raises(VendorError, match="authority_required"):
        await adapter.submit(prepared, approve(command))
    implementation.current_authority = True
    wrong_action = approve(command).model_copy(update={"action": "referral.submit"})
    with pytest.raises(VendorError, match="approval_changed"):
        await adapter.submit(prepared, wrong_action)
    assert implementation.effects == []
    uploaded = await adapter.submit(prepared, approve(command))
    referral = VendorCommand(selection=selection(), operation_id=uid(11), revision_id=uid(12), expires_at=command.expires_at,
        intent=PortalReferralIntent(portal_id=adapter.profile.portal_id, profile_sha256=adapter.profile.commitment(), correspondence=correspondence(),
            summary="Explicit synthetic referral summary", attachment=PortalAttachment(document=document(), reference=uploaded.reference)))
    with pytest.raises(VendorError, match="request_invalid"):
        registry.prepare(referral, PDF)
    with pytest.raises(VendorError, match="approval_changed"):
        await adapter.submit(registry.prepare(referral), approve(command))
    receipt = await adapter.submit(registry.prepare(referral), approve(referral))
    status = await adapter.observe(referral, receipt.reference)
    assert status.state == "pending" and len(implementation.effects) == 2
    assert all(item.external_acceptance is False for item in registry.capabilities(adapter.profile.portal_id))
    implementation.current_authority = False
    with pytest.raises(VendorError, match="authority_required"):
        await adapter.observe(referral, receipt.reference)
    with pytest.raises(VendorError, match="capability_unavailable"):
        PRODUCTION_PORTALS.resolve(selection(), adapter.profile.portal_id, "referral.submit")


@pytest.mark.parametrize("updates", [{"auth_scheme": "custom"}, {"auth_header": "Cookie"}, {"receipt_parser_version": ""},
    {"correspondence": ("practice", "recipient")}, {"correspondence": ("patient", "recipient")}, {"correspondence": ("patient", "practice")},
    {"routes": ()}, {"routes": (route("referral.read"), route("referral.read"))}])
def test_profile_requires_closed_auth_parser_correspondence_and_exact_capability_routes(updates):
    data = profile().model_dump(mode="python")
    data.update(updates)
    with pytest.raises(ValidationError):
        PortalProfile.model_validate(data)


@pytest.mark.parametrize("scheme,header", [("oauth2_bearer", "Authorization"), ("bearer_api_key", "Authorization"), ("basic", "Authorization"), ("x_api_key", "X-API-Key")])
def test_auth_headers_are_a_closed_scheme_mapping(scheme, header):
    data = profile().model_dump(mode="python")
    data["auth_scheme"] = scheme
    assert PortalProfile.model_validate(data).auth_header == header


@pytest.mark.parametrize("updates", [{"origin_index": 1}, {"origin_index": True}, {"capability": "message.submit"},
    {"idempotency": "documented_key_replay"}, {"idempotency_header": "Cookie"}, {"idempotency_header": "Idempotency-Key"},
    {"reconciliation": "not_applicable"}, {"method": "GET"}, {"request_contract_sha256": "unknown"}])
def test_route_classification_and_origin_are_bound_to_profile(updates):
    data = profile().model_dump(mode="python")
    routes = list(data["routes"])
    routes[1] = {**routes[1], **updates}
    data["routes"] = routes
    with pytest.raises(ValidationError):
        PortalProfile.model_validate(data)


@pytest.mark.parametrize("path", ["https://portal.example.invalid/x", "//outside.invalid/x", "/x/../y", "/x/./y", "/x?key=y", "/x#y", "/x/%2f", "/x/{arbitrary}", "/x/{reference}?q=1", "/x/", "/x//y"])
def test_fixed_route_template_is_not_a_url_query_or_path_traversal(path):
    data = route("referral.read").model_dump(mode="python")
    data["path_template"] = path
    with pytest.raises(ValidationError):
        PortalRoute.model_validate(data)


def test_route_ids_are_encoded_exactly_once_and_only_required_bindings_are_accepted():
    configured = route("referral.read")
    assert configured.render_path(PortalRouteBindings(reference="ZW50+/==")) == "/synthetic/referrals/ZW50%2B%2F%3D%3D"
    for bindings in [PortalRouteBindings(), PortalRouteBindings(reference="opaque", patient_id="extra")]:
        with pytest.raises(VendorError, match="request_invalid"):
            configured.render_path(bindings)
    for value in ["../x", "..", "%2F", "x?y", "x#y", "https://outside.invalid", "x\r\ny", "x" * 256]:
        with pytest.raises(ValidationError):
            PortalRouteBindings(reference=value)
    long_route = configured.model_copy(update={"path_template": "/" + "/".join(["{reference}"] * 16)})
    with pytest.raises(VendorError, match="request_invalid"):
        long_route.render_path(PortalRouteBindings(reference="/" * 255))


def test_registration_consistency_and_unsupported_operations_fail_before_preparation():
    implementation = SyntheticInMemoryPortal()
    with pytest.raises(VendorError, match="request_invalid"):
        PortalRegistry((PortalBinding(implementation.profile, SimpleNamespace(profile=implementation.profile)),))
    with pytest.raises(VendorError, match="request_invalid"):
        PortalRegistry((PortalBinding(implementation.profile, implementation), PortalBinding(implementation.profile, implementation)))
    registry = PortalRegistry((PortalBinding(implementation.profile, implementation),))
    with pytest.raises(VendorError, match="capability_unavailable"):
        registry.resolve(selection(), implementation.profile.portal_id, "message.submit")
    command = upload_command(implementation.profile)
    changed = command.model_copy(update={"intent": command.intent.model_copy(update={"profile_sha256": "0" * 64})})
    with pytest.raises(VendorError, match="connection_changed"):
        registry.prepare(changed, PDF)
    with pytest.raises(VendorError, match="artifact_changed"):
        registry.prepare(command, PDF + b"changed")
    implementation.profile = implementation.profile.model_copy(update={"receipt_parser_version": "changed"})
    with pytest.raises(VendorError, match="capability_unavailable"):
        registry.resolve(selection(), command.intent.portal_id, "document.upload")
    assert implementation.effects == []


def test_preparer_cannot_substitute_a_different_command_or_untyped_payload():
    implementation = SyntheticInMemoryPortal()
    registry = PortalRegistry((PortalBinding(implementation.profile, implementation),))
    command = upload_command(implementation.profile)
    changed = command.model_copy(update={"operation_id": uid(99)})
    implementation.prepare = lambda *_args: PreparedPortalRequest(command=changed, profile_sha256=implementation.profile.commitment(), document=PDF)
    with pytest.raises(VendorError, match="request_invalid"):
        registry.prepare(command, PDF)
    data = command.model_dump(mode="python")
    data["intent"]["body"] = {"arbitrary_vendor_write": True}
    with pytest.raises(ValidationError):
        VendorCommand.model_validate(data)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["account", "patient", "profile", "artifact"])
async def test_upload_reference_cannot_cross_account_patient_profile_or_artifact(change):
    implementation = SyntheticInMemoryPortal()
    implementation.enabled = implementation.current_authority = True
    command = upload_command(implementation.profile)
    receipt = await implementation.submit(implementation.prepare(command, PDF), approve(command))
    ref = receipt.reference
    updates = {"account": {"selection_sha256": "0" * 64}, "patient": {"correspondence_sha256": "0" * 64},
        "profile": {"portal_profile_sha256": "0" * 64}, "artifact": {"artifact_sha256": "0" * 64}}[change]
    with pytest.raises(ValidationError):
        VendorCommand(selection=selection(), operation_id=uid(11), revision_id=uid(12), expires_at=command.expires_at,
            intent=PortalReferralIntent(portal_id=implementation.profile.portal_id, profile_sha256=implementation.profile.commitment(), correspondence=correspondence(),
                summary="Explicit synthetic summary", attachment=PortalAttachment(document=document(), reference=ref.model_copy(update=updates))))
