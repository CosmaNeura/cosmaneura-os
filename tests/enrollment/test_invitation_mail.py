"""Invitation email notifier and invite response email_sent flag."""
from __future__ import annotations

from pydantic import SecretStr

from cosmas_os.enrollment.config import EnrollmentSettings
from cosmas_os.enrollment.mail import (
    DisabledInvitationNotifier,
    RecordingInvitationNotifier,
    WebhookInvitationNotifier,
    build_invitation_notifier,
)
from cosmas_os.enrollment.synthetic import synthetic_settings


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
    assert isinstance(build_invitation_notifier(enabled=False, webhook_url="", webhook_secret=""), DisabledInvitationNotifier)


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


def test_invitation_mail_configured_requires_https_webhook_and_secret():
    settings = EnrollmentSettings(
        invitation_mail_enabled=True,
        invitation_mail_webhook_url="https://mail.example.invalid/enrollment-invite",
        invitation_mail_webhook_secret=SecretStr("synthetic-invitation-mail-webhook-secret!!"),
    )
    assert settings.invitation_mail_configured() is True
    closed = synthetic_settings()
    assert closed.invitation_mail_configured() is False


def test_public_config_exposes_activation_blockers_and_client_install():
    settings = synthetic_settings()
    settings.activation_available = False
    settings.stripe_acquisition_enabled = False
    value = settings.public_config(database_ready=True, auth_ready=True, stripe_verified=True)
    assert value["activation_available"] is False
    assert value["pricing"]["first_human_cents"] == 30000
    assert value["pricing"]["additional_human_cents"] == 10000
    assert value["pricing"]["trial_days"] == 14
    assert value["client_install"]["open_chief_is_not_install"] is True
    assert value["invitation_email_configured"] is False
    assert any("ACTIVATION_AVAILABLE" in item for item in value["activation_blockers"])
    assert any("acquisition" in item.lower() for item in value["activation_blockers"])
