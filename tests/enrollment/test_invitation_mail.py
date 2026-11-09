"""Invitation email notifier, staging recipient allowlist, and invite email_sent."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from tests.enrollment.test_journey import accepted, mutate, signed, status

from cosmas_os.enrollment.config import EnrollmentSettings
from cosmas_os.enrollment.mail import (
    AllowlistedInvitationNotifier,
    DisabledInvitationNotifier,
    RecordingInvitationNotifier,
    WebhookInvitationNotifier,
    build_invitation_notifier,
    invitation_mail_recipient_allowed,
)
from cosmas_os.enrollment.models import Membership
from cosmas_os.enrollment.synthetic import create_synthetic_app, synthetic_settings


@pytest.fixture
def lab():
    app = create_synthetic_app()
    with TestClient(app) as client:
        yield app, client


def test_invitation_mail_enabled_defaults_off():
    settings = EnrollmentSettings()
    assert settings.invitation_mail_enabled is False
    assert settings.invitation_mail_allowed_recipients == []
    assert settings.invitation_mail_configured() is False
    closed = synthetic_settings()
    assert closed.invitation_mail_enabled is False
    assert closed.invitation_mail_configured() is False


def test_allowlist_accepts_example_invalid_and_exact_team_inboxes():
    assert invitation_mail_recipient_allowed("staff@example.invalid") is True
    assert invitation_mail_recipient_allowed("  Owner.Test@Example.Invalid  ") is True
    assert invitation_mail_recipient_allowed(
        "qa-invite@mail.cosmaneura.test",
        allowed_recipients=["qa-invite@mail.cosmaneura.test"],
    ) is True


def test_allowlist_refuses_real_looking_addresses():
    assert invitation_mail_recipient_allowed("staff@gmail.com") is False
    assert invitation_mail_recipient_allowed("owner@example.com") is False
    assert invitation_mail_recipient_allowed("person@cosmaneura.com") is False
    assert invitation_mail_recipient_allowed("staff@evil.example.invalid") is False
    assert invitation_mail_recipient_allowed("not-an-email") is False
    assert invitation_mail_recipient_allowed("") is False
    assert invitation_mail_recipient_allowed(
        "staff@gmail.com",
        allowed_recipients=["qa-invite@mail.cosmaneura.test"],
    ) is False


def test_allowlisted_notifier_refuses_before_inner_send():
    inner = RecordingInvitationNotifier()
    notifier = AllowlistedInvitationNotifier(
        inner,
        allowed_recipients=["qa-invite@mail.cosmaneura.test"],
    )
    assert notifier.send_invitation(
        to_email="stranger@gmail.com",
        practice_display_name="Invented Practice",
        invite_url="https://app.example.invalid/onboarding?invite=token",
        expires_at="2026-11-12T00:00:00+00:00",
        role="staff",
    ) is False
    assert inner.sent == []
    assert notifier.send_invitation(
        to_email="staff@example.invalid",
        practice_display_name="Invented Practice",
        invite_url="https://app.example.invalid/onboarding?invite=token",
        expires_at="2026-11-12T00:00:00+00:00",
        role="staff",
    ) is True
    assert inner.sent[0]["to_email"] == "staff@example.invalid"


def test_disabled_notifier_reports_false():
    assert DisabledInvitationNotifier().send_invitation(
        to_email="staff@example.invalid",
        practice_display_name="Invented Practice",
        invite_url="https://app.example.invalid/onboarding?invite=token",
        expires_at="2026-11-12T00:00:00+00:00",
        role="staff",
    ) is False


def test_recording_notifier_records_synthetic_delivery():
    notifier = RecordingInvitationNotifier()
    assert notifier.send_invitation(
        to_email="staff@example.invalid",
        practice_display_name="Invented Practice",
        invite_url="https://app.example.invalid/onboarding?invite=token",
        expires_at="2026-11-12T00:00:00+00:00",
        role="staff",
    ) is True
    assert notifier.sent[0]["to_email"] == "staff@example.invalid"


def test_build_notifier_stays_disabled_until_configured():
    assert isinstance(
        build_invitation_notifier(enabled=False, webhook_url="", webhook_secret=""),
        DisabledInvitationNotifier,
    )


def test_webhook_notifier_requires_https_and_long_secret():
    try:
        WebhookInvitationNotifier("http://example.invalid/hook", "x" * 32)
        raised = False
    except ValueError:
        raised = True
    assert raised
    try:
        WebhookInvitationNotifier("https://mail.example.invalid/hook", "short")
        raised = False
    except ValueError:
        raised = True
    assert raised


def test_invitation_mail_configured_requires_synthetic_https_webhook_and_secret():
    settings = EnrollmentSettings(
        data_mode="synthetic",
        invitation_mail_enabled=True,
        invitation_mail_webhook_url="https://mail.example.invalid/enrollment-invite",
        invitation_mail_webhook_secret=SecretStr("synthetic-invitation-mail-webhook-secret!!"),
    )
    assert settings.invitation_mail_configured() is True
    production = EnrollmentSettings(
        data_mode="production",
        invitation_mail_enabled=True,
        invitation_mail_webhook_url="https://mail.example.invalid/enrollment-invite",
        invitation_mail_webhook_secret=SecretStr("synthetic-invitation-mail-webhook-secret!!"),
    )
    assert production.invitation_mail_configured() is False
    closed = synthetic_settings()
    assert closed.invitation_mail_configured() is False


def test_public_config_exposes_activation_blockers_and_client_install():
    settings = synthetic_settings()
    settings.activation_available = False
    settings.stripe_acquisition_enabled = False
    value = settings.public_config(database_ready=True, auth_ready=True, stripe_verified=True)
    assert value["activation_available"] is False
    assert value["pricing"]["seat_cents"] == 30000
    assert value["pricing"]["max_self_serve_humans"] == 10
    assert value["pricing"]["trial_days"] == 14
    assert "first_human_cents" not in value["pricing"]
    assert "additional_human_cents" not in value["pricing"]
    assert value["client_install"]["open_chief_is_not_install"] is True
    assert value["invitation_email_configured"] is False
    assert any("ACTIVATION_AVAILABLE" in item for item in value["activation_blockers"])
    assert any("acquisition" in item.lower() for item in value["activation_blockers"])


def test_invite_hands_allowlisted_email_to_mailer_with_expected_content(lab):
    app, client = lab
    recorder = RecordingInvitationNotifier()
    service = app.state.enrollment_service
    service.settings.invitation_mail_enabled = True
    service.settings.invitation_mail_webhook_url = "https://mail.example.invalid/enrollment-invite"
    service.settings.invitation_mail_webhook_secret = SecretStr(
        "synthetic-invitation-mail-webhook-secret!!"
    )
    service.invitation_notifier = AllowlistedInvitationNotifier(recorder)
    owner = signed(client)
    accepted(client, owner, humans=2)
    invite = mutate(
        client,
        owner,
        "/invitations",
        {"email": "staff-a@example.invalid", "role": "staff", "can_sign": False},
    ).json()
    assert invite["email_sent"] is True
    assert len(recorder.sent) == 1
    payload = recorder.sent[0]
    assert payload["to_email"] == "staff-a@example.invalid"
    assert payload["practice_display_name"] == "Example Practice"
    assert payload["role"] == "staff"
    assert payload["invite_url"].startswith("https://app.example.invalid/onboarding?invite=")
    assert invite["token"] in payload["invite_url"]
    assert payload["expires_at"] == invite["expires_at"]


def test_invite_refuses_real_looking_recipient_without_sending(lab):
    app, client = lab
    recorder = RecordingInvitationNotifier()
    service = app.state.enrollment_service
    service.settings.invitation_mail_enabled = True
    service.settings.invitation_mail_webhook_url = "https://mail.example.invalid/enrollment-invite"
    service.settings.invitation_mail_webhook_secret = SecretStr(
        "synthetic-invitation-mail-webhook-secret!!"
    )
    service.invitation_notifier = AllowlistedInvitationNotifier(recorder)
    owner = signed(client)
    accepted(client, owner, humans=2)
    # Invitation record can still be created for the synthetic seat path; mail must not send
    # when a caller somehow supplies a real-looking address that is not allowlisted.
    # Enrollment invite validation still requires a normal email shape; use an invented
    # non-example.invalid address that the allowlist must refuse.
    invite = mutate(
        client,
        owner,
        "/invitations",
        {"email": "outside@example.com", "role": "staff", "can_sign": False},
    ).json()
    assert invite["email_sent"] is False
    assert recorder.sent == []
    assert "token" in invite


def test_invite_email_leaves_existing_members_unaffected(lab):
    app, client = lab
    recorder = RecordingInvitationNotifier()
    service = app.state.enrollment_service
    service.settings.invitation_mail_enabled = True
    service.settings.invitation_mail_webhook_url = "https://mail.example.invalid/enrollment-invite"
    service.settings.invitation_mail_webhook_secret = SecretStr(
        "synthetic-invitation-mail-webhook-secret!!"
    )
    service.invitation_notifier = AllowlistedInvitationNotifier(recorder)
    owner = signed(client)
    accepted(client, owner, humans=3)
    staff = signed(client, "staff-a")
    first = mutate(
        client,
        owner,
        "/invitations",
        {"email": "staff-a@example.invalid", "role": "staff", "can_sign": False},
    ).json()
    joined = mutate(client, staff, "/join", {"token": first["token"]}).json()
    assert joined["practice"]["role"] == "staff"
    owner_before = status(client, owner)
    second = mutate(
        client,
        owner,
        "/invitations",
        {"email": "signer-a@example.invalid", "role": "admin", "can_sign": True},
    ).json()
    assert second["email_sent"] is True
    owner_after = status(client, owner)
    assert owner_after["practice"]["role"] == "owner"
    assert owner_after["practice"]["id"] == owner_before["practice"]["id"]
    staff_after = status(client, staff)
    assert staff_after["practice"]["role"] == "staff"
    with service.sessions() as session:
        members = session.scalars(select(Membership).where(
            Membership.practice_id == owner_after["practice"]["id"],
            Membership.active.is_(True),
        )).all()
        roles = sorted(member.role for member in members)
        assert roles == ["owner", "staff"]
        assert all(member.active for member in members)
    assert len(recorder.sent) == 2
    assert {item["to_email"] for item in recorder.sent} == {
        "staff-a@example.invalid",
        "signer-a@example.invalid",
    }
