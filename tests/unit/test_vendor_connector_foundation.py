import asyncio
import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from cosmas_os.adapters.vendor_connectors.documo import DocumoConnector
from cosmas_os.adapters.vendor_connectors.documo import notification_hint as documo_hint
from cosmas_os.adapters.vendor_connectors.portals import (
    PRODUCTION_PORTALS,
    PortalBinding,
    PortalProfile,
    PortalRegistry,
    PortalRoute,
)
from cosmas_os.adapters.vendor_connectors.spruce import SpruceConnector
from cosmas_os.adapters.vendor_connectors.spruce import verify_webhook as spruce_event
from cosmas_os.adapters.vendor_connectors.srfax import SRFaxConnector
from cosmas_os.adapters.vendor_connectors.srfax import notification_hint as srfax_hint
from cosmas_os.adapters.vendor_connectors.stripe import StripeConnector
from cosmas_os.adapters.vendor_connectors.stripe import verify_webhook as stripe_event
from cosmas_os.adapters.vendor_connectors.transport import (
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    STRIPE_VERSION,
    Credential,
    VendorRuntime,
    WireRequest,
)
from cosmas_os.ports.vendor_connectors import (
    ApprovalBinding,
    CapabilityDescription,
    ConnectionSelection,
    DocumentBinding,
    EmailDestination,
    FaxIntent,
    MediaUploadIntent,
    PhoneDestination,
    ProviderReference,
    SecureDestination,
    SpruceMessageIntent,
    StripePaymentIntentIntent,
    UploadedMedia,
    VendorCommand,
    VendorError,
)

NOW = datetime(2026, 9, 21, 12, tzinfo=UTC)
PDF = b"%PDF-1.7\n% local synthetic byte-binding fixture; not a rendered/vendor-accepted PDF\n%%EOF"


def uid(n):
    return UUID(f"00000000-0000-4000-8000-{n:012d}")


def selection(vendor, environment=None):
    remote = str(uid(9)) if vendor == "documo" else "12345" if vendor == "srfax" else "acct_fixture" if vendor == "stripe" else "entity_fixture"
    return ConnectionSelection(vendor=vendor, connection_id=uid(1), box_id=uid(2), owner_id=uid(3),
        environment=environment or ("sandbox" if vendor in {"stripe", "documo"} else "production"),
        remote_account_id=remote, credential_ref=uid(4), configuration_sha256="a" * 64)


def document(data=PDF):
    return DocumentBinding(artifact_id=uid(5), sha256=hashlib.sha256(data).hexdigest(), byte_length=len(data))


def command(vendor, intent=None, **changes):
    if intent is None:
        intent = (SpruceMessageIntent(internal_endpoint_id="ZW50aXR5L2lk+/==", destination=SecureDestination(contact_id="entity_patient"), text="Invented follow-up")
            if vendor == "spruce" else StripePaymentIntentIntent(customer_id="cus_fixture", amount=1250)
            if vendor == "stripe" else FaxIntent(caller_id="2125550100", destination="12125550101",
                sender_email="fax@example.invalid" if vendor == "srfax" else None, document=document()))
    return VendorCommand(selection=selection(vendor), operation_id=uid(6), revision_id=uid(7),
        expires_at=NOW + timedelta(minutes=2), intent=intent, **changes)


def approval(cmd):
    return ApprovalBinding(operation_id=cmd.operation_id, revision_id=cmd.revision_id, action=cmd.intent.kind,
        approved_payload_sha256=cmd.commitment(), selection_sha256=cmd.selection.commitment(), expires_at=cmd.expires_at)


def payment(**changes):
    return {"object": "payment_intent", "id": "pi_fixture", "customer": "cus_fixture", "amount": 1250,
        "currency": "usd", "amount_received": 0, "livemode": False, "status": "requires_payment_method",
        "client_secret": "PRIVATE-NEVER-PROJECT", **changes}


def reply(vendor):
    return {"requestId": "asyncRequest_fixture"} if vendor == "spruce" else {"Status": "Success", "Result": "123456"} if vendor == "srfax" else {"messageId": str(uid(10))} if vendor == "documo" else payment()


def fixture(cmd, handler=None, *, enabled=True, timeout=30, authorize=None, clock=None):
    seen = SimpleNamespace(calls=[], credentials=0, authorities=0, now=NOW)

    async def credentials(selected):
        seen.credentials += 1
        return Credential(selection_sha256=selected.commitment(), credential_ref=str(selected.credential_ref),
            secret=SecretStr("sk_test_fixture_secret" if selected.vendor == "stripe" else "synthetic-only-secret"))

    async def allowed(*args):
        seen.authorities += 1
        return await authorize(*args) if authorize else True

    async def exchange(request):
        seen.calls.append(request)
        return await handler(request) if handler else httpx.Response(200, json=reply(cmd.selection.vendor))

    runtime = VendorRuntime(cmd.selection, credentials, enabled=enabled, authorize=allowed,
        transport=httpx.MockTransport(exchange), now=clock or (lambda: seen.now), timeout_seconds=timeout)
    connector = {"spruce": SpruceConnector, "srfax": SRFaxConnector, "documo": DocumoConnector, "stripe": StripeConnector}[cmd.selection.vendor](runtime)
    return connector, seen


async def submit(connector, cmd, auth=None, data=PDF):
    auth = auth or approval(cmd)
    if isinstance(cmd.intent, (FaxIntent, MediaUploadIntent)):
        return await connector.submit(cmd, auth, data)
    return await connector.submit(cmd, auth)


@pytest.mark.asyncio
@pytest.mark.parametrize("vendor", ["spruce", "srfax", "documo", "stripe"])
async def test_default_disabled_before_credentials_or_wire(vendor):
    cmd = command(vendor)
    connector, seen = fixture(cmd, enabled=False)
    assert VendorRuntime.__init__.__kwdefaults__["enabled"] is False
    with pytest.raises(VendorError, match="connector_disabled"):
        await submit(connector, cmd)
    assert not seen.calls and seen.credentials == seen.authorities == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("vendor", ["spruce", "srfax", "documo", "stripe"])
async def test_documented_submit_is_one_call_and_acceptance_not_completion(vendor):
    cmd = command(vendor)
    connector, seen = fixture(cmd)
    result = await submit(connector, cmd)
    assert result.state == "accepted", result
    assert result.reference.operation_id == cmd.operation_id
    assert result.request_sha256 == cmd.commitment()
    assert len(seen.calls) == 1 and seen.credentials == 1 and seen.authorities == 2
    req = seen.calls[0]
    assert req.url.scheme == "https" and req.method == "POST"
    assert b"PRIVATE-NEVER-PROJECT" not in result.model_dump_json().encode()
    assert "synthetic-only-secret" not in repr(result) and "Invented follow-up" not in repr(cmd)
    if vendor == "spruce":
        assert req.url.raw_path == b"/v1/internalendpoints/ZW50aXR5L2lk%2B%2F%3D%3D/conversations"
        assert json.loads(req.content) == {"destination": {"secureEndpoint": {"contactId": "entity_patient",
            "deliveryMethod": "only_conversations_matching_internal_endpoint"}},
            "message": {"body": [{"type": "text", "value": "Invented follow-up"}], "internal": False}}
        assert req.headers["s-idempotency-key"] == str(cmd.operation_id)
    elif vendor == "srfax":
        fields = parse_qs(req.content.decode())
        assert fields["action"] == ["Queue_Fax"] and fields["sFaxType"] == ["SINGLE"] and fields["sRetries"] == ["0"]
        assert base64.b64decode(fields["sFileContent_1"][0]) == PDF
        assert fields["access_id"] == ["12345"] and fields["access_pwd"] == ["synthetic-only-secret"]
        assert "sNotifyURL" not in fields and "sQueueFaxDate" not in fields
    elif vendor == "documo":
        assert req.url.host == "api.sandbox.documo.com" and req.url.path == "/v1/faxes"
        assert req.headers["Authorization"] == "Basic synthetic-only-secret"
        assert PDF in req.content and b'name="attachments"' in req.content and b"attachmentUrls" not in req.content
    else:
        fields = parse_qs(req.content.decode())
        assert fields == {"amount": ["1250"], "currency": ["usd"], "customer": ["cus_fixture"], "confirm": ["false"],
            "payment_method_types[]": ["card"], "metadata[cosmas_operation_id]": [str(cmd.operation_id)]}
        assert req.headers["Stripe-Version"] == STRIPE_VERSION and req.headers["Idempotency-Key"] == str(cmd.operation_id)


@pytest.mark.parametrize("bad", ["../endpoint", "https://outside.invalid", "abc?next=x", "%2F", "a#x", "a\r\nx"])
def test_spruce_endpoint_id_cannot_be_a_path_or_url(bad):
    with pytest.raises(ValidationError):
        SpruceMessageIntent(internal_endpoint_id=bad, destination=SecureDestination(contact_id="entity_test"), text="Test")


@pytest.mark.asyncio
@pytest.mark.parametrize("destination,field", [(PhoneDestination(channel="sms", number="+12125550101"), "smsOrEmailEndpoint"),
    (EmailDestination(address="person@example.invalid"), "smsOrEmailEndpoint")])
async def test_spruce_destinations_are_discriminated_and_send_no_extra_actions(destination, field):
    cmd = command("spruce", SpruceMessageIntent(internal_endpoint_id="ZW50==", destination=destination, text="Explicit message"))
    connector, seen = fixture(cmd)
    assert (await submit(connector, cmd)).state == "accepted"
    data = json.loads(seen.calls[0].content)
    assert set(data["destination"]) == {field}
    assert set(data) == {"destination", "message"} and "author" not in data["message"]


@pytest.mark.asyncio
async def test_media_upload_has_own_authority_and_exact_artifact_account_receipt():
    cmd = command("spruce", MediaUploadIntent(document=document()))

    async def media(_req):
        return httpx.Response(200, json={"id": str(uid(11)), "object": "media"})

    connector, seen = fixture(cmd, media)
    wrong = approval(command("spruce"))
    with pytest.raises(VendorError, match="approval_changed"):
        await submit(connector, cmd, wrong)
    assert seen.calls == []
    observation = await submit(connector, cmd)
    assert observation.state == "accepted" and observation.reference.artifact_sha256 == document().sha256
    assert seen.calls[0].url.path == "/v1/media" and b'name="media"' in seen.calls[0].content
    uploaded = UploadedMedia(document=document(), reference=observation.reference)
    fax = command("spruce", SpruceMessageIntent(internal_endpoint_id="ZW50==", destination=PhoneDestination(channel="fax", number="+12125550101"),
        text="", attachment=uploaded)).model_copy(update={"operation_id": uid(12)})
    second, second_seen = fixture(fax)
    assert (await submit(second, fax)).state == "accepted" and len(second_seen.calls) == 1
    assert second_seen.calls[0].url.path.endswith("/conversations")
    assert json.loads(second_seen.calls[0].content)["message"]["attachments"] == [{"attachmentId": str(uid(11)), "title": "document.pdf"}]
    altered = uploaded.model_copy(update={"document": document(PDF + b"changed")})
    with pytest.raises(ValidationError):
        UploadedMedia.model_validate(altered.model_dump())
    with pytest.raises(ValidationError):
        VendorCommand.model_validate({**fax.model_dump(), "selection": fax.selection.model_copy(update={"connection_id": uid(20)}).model_dump()})


@pytest.mark.asyncio
@pytest.mark.parametrize("vendor", ["srfax", "documo"])
async def test_changed_artifact_never_resolves_credentials(vendor):
    cmd = command(vendor)
    connector, seen = fixture(cmd)
    with pytest.raises(VendorError, match="artifact_changed"):
        await submit(connector, cmd, data=PDF + b"changed")
    assert seen.calls == [] and seen.credentials == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["operation", "revision", "hash", "selection", "expired", "action"])
async def test_changed_approval_denied_before_io(change):
    cmd = command("stripe")
    auth = approval(cmd)
    updates = {"operation": {"operation_id": uid(90)}, "revision": {"revision_id": uid(90)},
        "hash": {"approved_payload_sha256": "0" * 64}, "selection": {"selection_sha256": "0" * 64},
        "expired": {"expires_at": NOW}, "action": {"action": "media.upload"}}[change]
    connector, seen = fixture(cmd)
    with pytest.raises(VendorError):
        await submit(connector, cmd, auth.model_copy(update=updates))
    assert not seen.calls


@pytest.mark.asyncio
async def test_expiry_and_revocation_after_dispatch_retain_trusted_private_receipt():
    cmd = command("stripe")
    active = True
    seen = None

    async def authorize(*_args):
        return active

    async def handler(_req):
        nonlocal active
        active = False
        seen.now = NOW + timedelta(minutes=5)
        return httpx.Response(200, json=payment())

    connector, seen = fixture(cmd, handler, authorize=authorize)
    result = await submit(connector, cmd)
    assert result.state == "accepted" and result.observed_at > cmd.expires_at
    assert seen.authorities == 2 and len(seen.calls) == 1
    with pytest.raises(VendorError, match="authority_required"):
        await connector.observe(cmd, result.reference)
    assert len(seen.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("vendor", ["spruce", "srfax", "documo", "stripe"])
async def test_lost_response_is_unconfirmed_and_never_retried(vendor):
    cmd = command(vendor)

    async def lost(_req):
        raise httpx.ReadTimeout("PRIVATE provider detail after injected acceptance")

    connector, seen = fixture(cmd, lost)
    result = await submit(connector, cmd)
    assert result.state == "unconfirmed" and result.reference is None
    assert len(seen.calls) == 1 and "PRIVATE" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_spruce_duplicate_422_never_becomes_success_or_new_key():
    cmd = command("spruce")
    connector, seen = fixture(cmd, lambda _req: asyncio.sleep(0, result=httpx.Response(422, json={"message": "duplicate"})))
    result = await submit(connector, cmd)
    assert result.state == "unconfirmed" and result.safe_error == "duplicate_unresolved" and result.reference is None
    assert len(seen.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(302, headers={"Location": "https://outside.invalid/secret"}),
    httpx.Response(200, content=b'{"requestId":"a","requestId":"b"}', headers={"Content-Type": "application/json"}),
    httpx.Response(200, content=b"\xff", headers={"Content-Type": "application/json"}),
    httpx.Response(200, content=b"x" * (MAX_RESPONSE_BYTES + 1), headers={"Content-Type": "application/json"}),
    httpx.Response(200, content=b"{}", headers={"Content-Type": "text/plain"}),
    httpx.Response(500, json={"private": "provider-detail"})])
async def test_invalid_or_ambiguous_response_never_delivers(response):
    cmd = command("spruce")
    connector, seen = fixture(cmd, lambda _req: asyncio.sleep(0, result=response))
    result = await submit(connector, cmd)
    assert result.state == "unconfirmed" and result.reference is None and len(seen.calls) == 1
    assert "provider-detail" not in result.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize("vendor", ["spruce", "srfax", "documo", "stripe"])
@pytest.mark.parametrize("status,body", [(400, {}), (401, {"unrelated": True}), (403, {"message": "PRIVATE unknown error"}), (404, {"Status": "Failed"})])
async def test_undocumented_json_4xx_is_not_authoritative_rejection_or_permission_to_retry(vendor, status, body):
    cmd = command(vendor)
    connector, seen = fixture(cmd, lambda _req: asyncio.sleep(0, result=httpx.Response(status, json=body)))
    result = await submit(connector, cmd)
    assert result.state == "unconfirmed" and result.reference is None
    assert result.safe_error == "response_invalid" and len(seen.calls) == 1
    assert result.response_sha256 and "PRIVATE" not in result.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize("body,state", [({"Status": "Failed"}, "unconfirmed"), ({"Status": "Failed", "Result": {}}, "unconfirmed"),
    ({"Status": "Failed", "Result": ""}, "unconfirmed"), ({"Status": "Failed", "Result": "PRIVATE invented documented rejection"}, "rejected")])
async def test_srfax_rejection_requires_documented_status_and_result_shape(body, state):
    cmd = command("srfax")
    connector, seen = fixture(cmd, lambda _req: asyncio.sleep(0, result=httpx.Response(200, json=body)))
    result = await submit(connector, cmd)
    assert result.state == state and result.reference is None and len(seen.calls) == 1
    assert "PRIVATE" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_response_json_and_srfax_expansion_limits_precede_success_or_credentials():
    data = b"%PDF-" + b"\xff" * (8_388_608 - 5)
    cmd = command("srfax", FaxIntent(caller_id="2125550100", destination="12125550101", sender_email="fax@example.invalid", document=document(data)))
    connector, seen = fixture(cmd)
    assert len(connector.prepare(cmd, data).body) > MAX_REQUEST_BYTES
    with pytest.raises(VendorError, match="request_invalid"):
        await submit(connector, cmd, data=data)
    assert seen.credentials == 0 and not seen.calls


@pytest.mark.asyncio
async def test_deadline_includes_credential_and_upstream_without_second_call():
    cmd = command("stripe")

    async def stalled(_req):
        await asyncio.sleep(1)
        return httpx.Response(200, json=payment())

    connector, seen = fixture(cmd, stalled, timeout=0.01)
    result = await submit(connector, cmd)
    assert result.state == "unconfirmed" and len(seen.calls) == 1
    second, second_seen = fixture(cmd, timeout=0.01)

    async def no_credential(_selection):
        await asyncio.sleep(1)

    second.runtime.credentials = no_credential
    with pytest.raises(VendorError, match="authority_required"):
        await submit(second, cmd)
    assert second_seen.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("vendor", ["srfax", "documo", "stripe"])
async def test_exact_reference_read_validates_current_result_and_ignores_old_approval_expiry(vendor):
    cmd = command(vendor)
    connector, seen = fixture(cmd)
    accepted = await submit(connector, cmd)
    assert accepted.reference is not None

    async def read(_req):
        if vendor == "srfax":
            return httpx.Response(200, json={"Status": "Success", "Result": {"ToFaxNumber": "12125550101", "SentStatus": "Sent", "Pages": 1}})
        if vendor == "documo":
            return httpx.Response(200, json={"messageId": str(uid(10)), "accountId": str(uid(9)), "direction": "outbound", "faxNumber": "+12125550101",
                "pagesCount": 1, "pagesComplete": 1, "status": "success", "resultCode": "0", "users": [{"private": "not-projected"}]})
        return httpx.Response(200, json=payment(status="succeeded", amount_received=1250))

    reader, reads = fixture(cmd, read, clock=lambda: NOW + timedelta(days=1))
    result = await reader.observe(cmd, accepted.reference)
    assert result.state == ("succeeded" if vendor == "stripe" else "transport_delivered")
    assert "not-projected" not in result.model_dump_json() and "PRIVATE-NEVER-PROJECT" not in result.model_dump_json()
    assert len(reads.calls) == 1
    wrong = accepted.reference.model_copy(update={"operation_id": uid(99)})
    with pytest.raises(VendorError, match="reference_unavailable"):
        await reader.observe(cmd, wrong)
    assert len(reads.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [{"customer": "cus_other"}, {"amount": True}, {"amount": 1251},
    {"currency": "eur"}, {"livemode": True}, {"status": "referral_completed"}, {"amount_received": 1300},
    {"status": "succeeded", "amount_received": 0}])
async def test_stripe_wrong_scope_amount_state_never_becomes_acceptance(changes):
    cmd = command("stripe")
    connector, _ = fixture(cmd, lambda _req: asyncio.sleep(0, result=httpx.Response(200, json=payment(**changes))))
    assert (await submit(connector, cmd)).state == "unconfirmed"


@pytest.mark.parametrize("value", [True, "50", 49, 100_000_000])
def test_payment_amount_is_strict_bounded_cents(value):
    with pytest.raises(ValidationError):
        StripePaymentIntentIntent(customer_id="cus_fixture", amount=value)


def test_spruce_signature_exact_raw_bytes_without_invented_event_id():
    raw = json.dumps({"object": "event", "type": "conversationItem.created", "eventTime": NOW.isoformat(),
        "data": {"object": {"id": "ti_fixture", "requestId": "asyncRequest_fixture", "text": "private omitted"}}}).encode()
    secret = b"synthetic-webhook-secret"
    signature = base64.b64encode(hmac.digest(secret, raw, "sha256")).decode()
    event = spruce_event(raw, signature, secret, selection("spruce"), NOW)
    assert event.authenticity == "signature_verified" and event.event_id is None
    assert event.request_id == "asyncRequest_fixture" and "private omitted" not in event.model_dump_json()
    for body, key, sign in [(raw + b" ", secret, signature), (raw, b"other", signature), (raw, secret, "notbase64")]:
        with pytest.raises(VendorError, match="signature_invalid"):
            spruce_event(body, sign, key, selection("spruce"), NOW)


def stripe_fixture_event():
    return json.dumps({"object": "event", "id": "evt_fixture", "type": "payment_intent.succeeded", "api_version": STRIPE_VERSION,
        "livemode": False, "data": {"object": payment(status="succeeded", amount_received=1250)}}).encode()


def test_stripe_signature_timestamp_rotation_and_body_binding():
    raw = stripe_fixture_event()
    secret = b"whsec_synthetic"
    timestamp = str(int(NOW.timestamp()))
    signed = hmac.new(secret, timestamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
    header = f"t={timestamp},v1={'0' * 64},v1={signed},v0=obsolete"
    event = stripe_event(raw, header, secret, selection("stripe"), NOW)
    assert event.event_id == "evt_fixture" and event.object_id == "pi_fixture"
    assert "PRIVATE" not in event.model_dump_json()
    for bad in [header + f",t={timestamp}", f"t={timestamp},v0={signed}", "t=abc,v1=" + signed, header + ",v1=invalid"]:
        with pytest.raises(VendorError, match="signature_invalid"):
            stripe_event(raw, bad, secret, selection("stripe"), NOW)
    for moment in [NOW + timedelta(seconds=301), NOW - timedelta(seconds=301)]:
        with pytest.raises(VendorError, match="signature_invalid"):
            stripe_event(raw, header, secret, selection("stripe"), moment)
    for body, key in [(raw + b" ", secret), (raw, b"different")]:
        with pytest.raises(VendorError, match="signature_invalid"):
            stripe_event(body, header, key, selection("stripe"), NOW)


def test_unsigned_fax_callbacks_are_only_hints_even_with_success_payload():
    first = srfax_hint(b"FaxDetailsID=123456&SentStatus=Sent&ToFaxNumber=12125550101", selection("srfax"), NOW)
    second = documo_hint(json.dumps({"messageId": str(uid(10)), "status": "success"}).encode(), selection("documo"), NOW)
    for result in [first, second]:
        assert result.authenticity == "untrusted_hint"
        assert "transport_delivered" not in result.model_dump_json()


@pytest.mark.parametrize("origin", ["https://127.0.0.1", "https://localhost", "https://example.invalid:443",
    "http://example.invalid", "https://user@example.invalid", "https://example.invalid/", "https://example.invalid/path",
    "https://*.example.invalid", "https://example.local", "https://example.invalid?secret=x"])
def test_portal_origin_is_not_a_generic_url_or_local_access(origin):
    with pytest.raises(ValidationError):
        PortalProfile(portal_id="example", contract_version="1", documentation_sha256="a" * 64, origins=(origin,), capabilities=(),
            auth_scheme="oauth2_bearer", correspondence=("patient", "practice"), receipt_parser_version="1", routes=())


def test_portal_registry_is_empty_until_explicit_per_portal_binding_and_never_grants_a_write():
    selected = selection("portal")
    with pytest.raises(VendorError, match="capability_unavailable"):
        PRODUCTION_PORTALS.resolve(selected, "any-portal", "referral.submit")
    profile = PortalProfile(portal_id="synthetic", contract_version="1", documentation_sha256="a" * 64,
        origins=("https://portal.example.invalid",), capabilities=(CapabilityDescription(capability="referral.read", evidence="documented"),),
        auth_scheme="oauth2_bearer", correspondence=("patient", "practice"), receipt_parser_version="1", routes=(PortalRoute(
            capability="referral.read", origin_index=0, method="GET", path_template="/referrals/{reference}", idempotency="read_only",
            reconciliation="not_applicable", request_contract_sha256="a" * 64, response_contract_sha256="b" * 64),))

    async def never(*_args):
        raise VendorError("capability_unavailable")

    implementation = SimpleNamespace(profile=profile, prepare=lambda *_args: None, submit=never, observe=never)
    registry = PortalRegistry((PortalBinding(profile, implementation),))
    assert registry.resolve(selected, "synthetic", "referral.read") is implementation
    with pytest.raises(VendorError, match="capability_unavailable"):
        registry.resolve(selected, "synthetic", "referral.submit")
    assert registry.capabilities("synthetic")[0].external_acceptance is False


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["missing_authority", "denied", "credential_selection", "credential_ref", "mode", "secret_header", "expired_during_credentials", "revoked_during_credentials", "private_exception"])
async def test_pre_dispatch_authority_and_credential_failures_never_send(failure):
    cmd = command("stripe")
    connector, seen = fixture(cmd)
    original_credentials = connector.runtime.credentials

    async def credentials(selected):
        result = await original_credentials(selected)
        if failure == "credential_selection":
            return result.model_copy(update={"selection_sha256": "0" * 64})
        if failure == "credential_ref":
            return result.model_copy(update={"credential_ref": str(uid(88))})
        if failure in {"mode", "secret_header"}:
            return result.model_copy(update={"secret": SecretStr("sk_live_wrong_mode" if failure == "mode" else "sk_test_x\r\nprivate")})
        if failure == "expired_during_credentials":
            seen.now = cmd.expires_at
        if failure == "revoked_during_credentials":
            connector.runtime.authorize = lambda *_args: asyncio.sleep(0, result=False)
        if failure == "private_exception":
            raise KeyError("PRIVATE credential storage content")
        return result

    connector.runtime.credentials = credentials
    if failure == "missing_authority":
        connector.runtime.authorize = None
    if failure == "denied":
        connector.runtime.authorize = lambda *_args: asyncio.sleep(0, result=False)
    with pytest.raises(VendorError) as error:
        await submit(connector, cmd)
    assert seen.calls == [] and error.value.attempted is False and "PRIVATE" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("vendor", ["spruce", "srfax"])
async def test_undocumented_sandbox_is_never_an_implied_production_fallback(vendor):
    cmd = command(vendor).model_copy(update={"selection": selection(vendor, "sandbox")})
    connector, seen = fixture(cmd)
    with pytest.raises(VendorError, match="capability_unavailable"):
        await submit(connector, cmd)
    assert seen.credentials == 0 and not seen.calls


@pytest.mark.asyncio
async def test_no_wire_body_content_type_headers_or_parser_dispatch_interface():
    cmd = command("stripe")
    connector, seen = fixture(cmd)
    wire = connector.prepare(cmd)
    assert not hasattr(connector.runtime, "submit") and not hasattr(connector.runtime, "exchange")
    forged = WireRequest(wire.method, wire.path, b"amount=9999&confirm=true", "application/x-www-form-urlencoded",
        wire.headers + (("Stripe-Account", "acct_other"),))
    for kwargs in [{"wire": forged}, {"body": forged.body}, {"content_type": "application/json"}, {"headers": forged.headers}]:
        with pytest.raises(TypeError):
            await connector.runtime._exchange(cmd, approval(cmd), mutating=True, **kwargs)
    with pytest.raises(TypeError):
        await connector.runtime._submit(cmd, approval(cmd), parse=lambda *_args: "forged acceptance")
    assert seen.credentials == 0 and not seen.calls
    fax = command("srfax")
    fax_connector, fax_seen = fixture(fax)
    with pytest.raises(VendorError, match="request_invalid"):
        await fax_connector.runtime._exchange(fax, document=PDF, mutating=False)
    assert fax_seen.credentials == 0 and not fax_seen.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("vendor", ["spruce", "srfax", "documo", "stripe"])
async def test_approved_a_cannot_dispatch_b_even_with_a_modified_preview(vendor):
    cmd = command(vendor)
    connector, seen = fixture(cmd)
    if vendor == "spruce":
        other = cmd.model_copy(update={"intent": cmd.intent.model_copy(update={"text": "Unapproved replacement"})})
        other_wire = connector.prepare(other)
        approved_wire = connector.prepare(cmd)
    elif vendor == "stripe":
        other = cmd.model_copy(update={"intent": cmd.intent.model_copy(update={"amount": 9999})})
        other_wire = connector.prepare(other)
        approved_wire = connector.prepare(cmd)
    else:
        other = cmd.model_copy(update={"intent": cmd.intent.model_copy(update={"destination": "12125550199"})})
        other_wire = connector.prepare(other, PDF)
        approved_wire = connector.prepare(cmd, PDF)
    assert other_wire.body != approved_wire.body
    with pytest.raises(VendorError, match="approval_changed"):
        await submit(connector, other, approval(cmd))
    assert not seen.calls
    # Public prepare is a preview, not the encoder injected into dispatch.
    connector.prepare = lambda *_args: other_wire
    connector._parse_submission = lambda *_args: "forged acceptance"
    result = await submit(connector, cmd)
    assert result.state == "accepted" and result.request_sha256 == cmd.commitment()
    sent = seen.calls[0].content
    assert sent == approved_wire.body or vendor == "srfax" and sent.startswith(approved_wire.body + b"&access_id=")


@pytest.mark.asyncio
async def test_caller_parser_cannot_turn_wrong_provider_receipt_into_acceptance():
    cmd = command("stripe")
    connector, _ = fixture(cmd, lambda _req: asyncio.sleep(0, result=httpx.Response(200, json=payment(amount=9999))))
    connector._parse_submission = lambda *_args: "forged acceptance"
    assert (await submit(connector, cmd)).state == "unconfirmed"


@pytest.mark.asyncio
async def test_post_dispatch_internal_failure_does_not_claim_no_attempt():
    cmd = command("stripe")
    clock = [NOW]

    async def handler(_req):
        clock[0] = None
        return httpx.Response(200, json=payment())

    connector, seen = fixture(cmd, handler, clock=lambda: clock[0])
    result = await submit(connector, cmd)
    assert result.state == "unconfirmed" and result.reference is None and len(seen.calls) == 1
    assert result.observed_at == NOW


@pytest.mark.asyncio
async def test_concrete_connector_cannot_dispatch_another_vendor_intent():
    cmd = command("stripe")
    connector, seen = fixture(cmd)
    with pytest.raises(VendorError, match="capability_unavailable"):
        await SpruceConnector(connector.runtime).submit(cmd, approval(cmd))
    assert not seen.calls and seen.credentials == 0


class ChunkedResponse(httpx.AsyncByteStream):
    def __init__(self, chunks, *, delay=0, close_error=None):
        self.chunks, self.delay, self.close_error = chunks, delay, close_error

    async def __aiter__(self):
        for chunk in self.chunks:
            if self.delay:
                await asyncio.sleep(self.delay)
            yield chunk

    async def aclose(self):
        if self.close_error:
            raise self.close_error


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["chunked", "oversized", "stalled", "compressed"])
async def test_streamed_body_has_one_shared_size_and_deadline_bound(case):
    cmd = command("stripe")
    body = json.dumps(payment()).encode()
    chunks = [body[:10], body[10:]] if case != "oversized" else [b" " * MAX_RESPONSE_BYTES, b"x"]
    headers = {"Content-Type": "application/json"}
    if case == "compressed":
        headers["Content-Encoding"] = "gzip"

    async def handler(_request):
        return httpx.Response(200, headers=headers, stream=ChunkedResponse(chunks, delay=1 if case == "stalled" else 0))

    connector, seen = fixture(cmd, handler, timeout=0.02)
    result = await submit(connector, cmd)
    assert result.state == ("accepted" if case == "chunked" else "unconfirmed")
    assert len(seen.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [RuntimeError("PRIVATE cleanup error"), VendorError("authority_required"), asyncio.CancelledError()])
async def test_complete_receipt_survives_late_transport_cleanup_failure(error):
    cmd = command("stripe")

    async def handler(_request):
        return httpx.Response(200, headers={"Content-Type": "application/json"}, stream=ChunkedResponse([json.dumps(payment()).encode()], close_error=error))

    connector, seen = fixture(cmd, handler)
    result = await submit(connector, cmd)
    assert result.state == "accepted" and result.response_sha256 and len(seen.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("changes,expected", [({"accountId": str(uid(89))}, "invalid"), ({"faxNumber": "+12125550102"}, "invalid"),
    ({"direction": "inbound"}, "invalid"), ({"messageId": str(uid(89))}, "invalid"),
    ({"pagesComplete": 2}, "invalid"), ({"pagesComplete": True}, "invalid"), ({"pagesComplete": 0}, "unknown"),
    ({"pagesComplete": 0, "pagesCount": 0}, "unknown"), ({"resultCode": "1"}, "unknown"), ({"status": "invented_success"}, "unknown"),
    ({"status": "transmitting", "pagesComplete": 0}, "pending")])
async def test_documo_completion_requires_exact_account_destination_and_complete_pages(changes, expected):
    cmd = command("documo")
    creator, _ = fixture(cmd)
    ref = (await submit(creator, cmd)).reference
    data = {"messageId": str(uid(10)), "accountId": str(uid(9)), "direction": "outbound", "faxNumber": "+12125550101",
        "pagesCount": 1, "pagesComplete": 1, "status": "success", "resultCode": "0", **changes}
    reader, _ = fixture(cmd, lambda _req: asyncio.sleep(0, result=httpx.Response(200, json=data)))
    if expected == "invalid":
        with pytest.raises(VendorError, match="response_invalid"):
            await reader.observe(cmd, ref)
    else:
        assert (await reader.observe(cmd, ref)).state == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("changes,expected", [({"ToFaxNumber": "12125550102"}, "invalid"), ({"Pages": "1"}, "invalid"),
    ({"Pages": None}, "unknown"), ({"Pages": 0}, "unknown"), ({"SentStatus": "Future Success"}, "unknown"),
    ({"SentStatus": "Failed"}, "transport_failed"), ({"SentStatus": "Sending Email"}, "pending")])
async def test_srfax_status_never_infers_destination_or_unsent(changes, expected):
    cmd = command("srfax")
    creator, _ = fixture(cmd)
    ref = (await submit(creator, cmd)).reference
    data = {"Status": "Success", "Result": {"ToFaxNumber": "12125550101", "SentStatus": "Sent", "Pages": 1, **changes}}
    reader, _ = fixture(cmd, lambda _req: asyncio.sleep(0, result=httpx.Response(200, json=data)))
    if expected == "invalid":
        with pytest.raises(VendorError, match="response_invalid"):
            await reader.observe(cmd, ref)
    else:
        assert (await reader.observe(cmd, ref)).state == expected


@pytest.mark.asyncio
async def test_spruce_current_item_must_correlate_but_still_does_not_prove_delivery():
    cmd = command("spruce")
    ref = ProviderReference(vendor="spruce", connection_id=cmd.selection.connection_id, environment="production",
        selection_sha256=cmd.selection.commitment(), operation_id=cmd.operation_id, request_sha256=cmd.commitment(),
        kind="conversation_item", value="ti_fixture", request_id="asyncRequest_fixture", observed_at=NOW)
    data = {"conversationItem": {"id": ref.value, "requestId": ref.request_id, "direction": "outbound", "isInternalNote": False}}
    reader, _ = fixture(cmd, lambda _req: asyncio.sleep(0, result=httpx.Response(200, json=data)))
    assert (await reader.observe(cmd, ref)).state == "pending"
    for changes in [{"requestId": "asyncRequest_other"}, {"isInternalNote": True}, {"direction": "inbound"}, {"id": "ti_other"}]:
        wrong = {"conversationItem": {**data["conversationItem"], **changes}}
        connector, _ = fixture(cmd, lambda _req, value=wrong: asyncio.sleep(0, result=httpx.Response(200, json=value)))
        with pytest.raises(VendorError, match="response_invalid"):
            await connector.observe(cmd, ref)


@pytest.mark.parametrize("value", [False, 0, "1720000000", 1720000000, "2026-09-21T12:00:00", NOW.replace(tzinfo=None)])
def test_command_expiry_requires_an_explicit_aware_timestamp(value):
    data = command("stripe").model_dump()
    data["expires_at"] = value
    with pytest.raises(ValidationError):
        VendorCommand.model_validate(data)


@pytest.mark.parametrize("origin", ["https://127.1", "https://0177.0.0.1", "https://0x7f.0.0.1", "https://foo.localhost", "https://foo.internal", "https://foo.home"])
def test_portal_profiles_reject_ip_aliases_and_local_dns_suffixes(origin):
    with pytest.raises(ValidationError):
        PortalProfile(portal_id="synthetic", contract_version="1", documentation_sha256="a" * 64, origins=(origin,), capabilities=(),
            auth_scheme="oauth2_bearer", correspondence=("patient", "practice"), receipt_parser_version="1", routes=())


def test_no_coerced_acceptance_boolean_or_unbounded_error_detail():
    for value in [0, "false", True]:
        with pytest.raises(ValidationError):
            CapabilityDescription(capability="referral.read", evidence="documented", external_acceptance=value)
    assert str(VendorError("PRIVATE provider data")) == "request_invalid"


@pytest.mark.asyncio
@pytest.mark.parametrize("vendor,lost", [("spruce", False), ("srfax", False), ("documo", False), ("stripe", False), ("stripe", True)])
async def test_real_loopback_http_serializes_exact_request_and_never_retries_lost_reply(vendor, lost):
    """Actual ephemeral TCP, with a test-only fixed-origin transport remap.

    This qualifies local HTTP encoding/observation, never remote TLS, vendor
    acceptance or a real send. No runtime product URL override is introduced.
    """
    cmd = command(vendor)
    observed = []
    tasks = set()

    async def serve(reader, writer):
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 3)
            lines = head.decode("ascii").split("\r\n")
            headers = dict(line.split(": ", 1) for line in lines[1:] if line)
            length = int(next(value for key, value in headers.items() if key.lower() == "content-length"))
            assert 0 < length <= MAX_REQUEST_BYTES
            body = await asyncio.wait_for(reader.readexactly(length), 3)
            observed.append((lines[0], headers, body))
            if not lost:
                payload = json.dumps(reply(vendor)).encode()
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: " + str(len(payload)).encode() + b"\r\n\r\n" + payload)
                await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    def connected(reader, writer):
        task = asyncio.create_task(serve(reader, writer))
        tasks.add(task)

    server = await asyncio.start_server(connected, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    class LoopbackOnly(httpx.AsyncBaseTransport):
        def __init__(self):
            self.local = httpx.AsyncHTTPTransport(retries=0)

        async def handle_async_request(self, request):
            assert request.url.scheme == "https"
            assert request.url.host == {"spruce": "api.sprucehealth.com", "srfax": "secure.srfax.com",
                "documo": "api.sandbox.documo.com", "stripe": "api.stripe.com"}[vendor]
            local_url = request.url.copy_with(scheme="http", host="127.0.0.1", port=port)
            local = httpx.Request(request.method, local_url, headers=request.headers, content=await request.aread())
            return await self.local.handle_async_request(local)

        async def aclose(self):
            await self.local.aclose()

    try:
        connector, _ = fixture(cmd)
        connector.runtime.transport = LoopbackOnly()
        result = await submit(connector, cmd)
    finally:
        server.close()
        await server.wait_closed()
        if tasks:
            await asyncio.gather(*tasks)
    assert len(observed) == 1
    assert result.state == ("unconfirmed" if lost else "accepted")
    line, headers, body = observed[0]
    assert line.startswith("POST ") and line.endswith(" HTTP/1.1")
    if vendor == "spruce":
        assert "%2B%2F%3D%3D" in line and json.loads(body)["message"]["internal"] is False
    elif vendor == "srfax":
        data = parse_qs(body.decode())
        assert data["action"] == ["Queue_Fax"] and base64.b64decode(data["sFileContent_1"][0]) == PDF
    elif vendor == "documo":
        assert PDF in body and b'name="attachments"' in body
    else:
        assert parse_qs(body.decode())["confirm"] == ["false"]
    assert "PRIVATE" not in result.model_dump_json()
