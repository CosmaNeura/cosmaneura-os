"""Invitation email delivery for CosmaBot enrollment.

Disabled by default. When enabled on synthetic staging, posts a structured
invite to the operator's HTTPS mail webhook only for allowlisted recipients
(`@example.invalid` or exact team test inboxes). Secret values never appear in
the payload body beyond the signed authorization header. Production mail stays
dark: the notifier is never built when data_mode is not synthetic.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import urllib.error
import urllib.request
from collections.abc import Sequence
from typing import Protocol
from urllib.parse import urlparse

# Fail-closed synthetic domain. Real-looking domains never match this.
SYNTHETIC_INVITE_RECIPIENT_DOMAIN = "example.invalid"


def invitation_mail_recipient_allowed(
    email: str,
    *,
    allowed_recipients: Sequence[str] = (),
) -> bool:
    """Return True only for `@example.invalid` or exact allowlisted test inboxes."""
    value = (email or "").strip().lower()
    if not value or value.count("@") != 1:
        return False
    local, _, domain = value.partition("@")
    if not local or not domain:
        return False
    if ".." in domain or domain.startswith(".") or domain.endswith("."):
        return False
    if domain == SYNTHETIC_INVITE_RECIPIENT_DOMAIN:
        return True
    allowed = {
        item.strip().lower()
        for item in allowed_recipients
        if isinstance(item, str) and item.strip()
    }
    return value in allowed


class InvitationNotifier(Protocol):
    def send_invitation(
        self,
        *,
        to_email: str,
        practice_display_name: str,
        invite_url: str,
        expires_at: str,
        role: str,
    ) -> bool: ...


class DisabledInvitationNotifier:
    def send_invitation(self, **_kwargs: object) -> bool:
        return False


class RecordingInvitationNotifier:
    """Synthetic / test notifier that records successful sends."""

    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    def send_invitation(
        self,
        *,
        to_email: str,
        practice_display_name: str,
        invite_url: str,
        expires_at: str,
        role: str,
    ) -> bool:
        self.sent.append({
            "to_email": to_email,
            "practice_display_name": practice_display_name,
            "invite_url": invite_url,
            "expires_at": expires_at,
            "role": role,
        })
        return True


class AllowlistedInvitationNotifier:
    """Fail-closed wrapper: refuse non-allowlisted recipients before the inner notifier."""

    def __init__(
        self,
        inner: InvitationNotifier,
        *,
        allowed_recipients: Sequence[str] = (),
    ) -> None:
        self._inner = inner
        self._allowed_recipients = tuple(allowed_recipients)

    def send_invitation(
        self,
        *,
        to_email: str,
        practice_display_name: str,
        invite_url: str,
        expires_at: str,
        role: str,
    ) -> bool:
        if not invitation_mail_recipient_allowed(
            to_email,
            allowed_recipients=self._allowed_recipients,
        ):
            return False
        return self._inner.send_invitation(
            to_email=to_email,
            practice_display_name=practice_display_name,
            invite_url=invite_url,
            expires_at=expires_at,
            role=role,
        )


class WebhookInvitationNotifier:
    """Operator-owned HTTPS webhook that actually delivers the invitation email."""

    def __init__(
        self,
        url: str,
        secret: str,
        *,
        timeout_seconds: float = 8.0,
        allowed_recipients: Sequence[str] = (),
    ):
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Invitation mail webhook must be an exact HTTPS URL.")
        if len(secret) < 32:
            raise ValueError("Invitation mail webhook secret must be at least 32 characters.")
        self._url, self._secret, self._timeout = url, secret, timeout_seconds
        self._allowed_recipients = tuple(allowed_recipients)

    def send_invitation(
        self,
        *,
        to_email: str,
        practice_display_name: str,
        invite_url: str,
        expires_at: str,
        role: str,
    ) -> bool:
        if not invitation_mail_recipient_allowed(
            to_email,
            allowed_recipients=self._allowed_recipients,
        ):
            return False
        body = json.dumps({
            "contract_version": "cosmas-enrollment-invitation-mail.v1",
            "to_email": to_email,
            "practice_display_name": practice_display_name,
            "invite_url": invite_url,
            "expires_at": expires_at,
            "role": role,
            "subject": f"You're invited to {practice_display_name} on CosmaBot",
        }, separators=(",", ":"), sort_keys=True).encode()
        digest = hmac.new(self._secret.encode(), body, hashlib.sha256).hexdigest()
        request = urllib.request.Request(
            self._url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "cosmas-enrollment-invitation-mail/1",
                "X-Cosmas-Enrollment-Mail-Signature": "sha256=" + digest,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return 200 <= int(response.status) < 300
        except (urllib.error.URLError, TimeoutError, ValueError):
            return False


def build_invitation_notifier(
    *,
    enabled: bool,
    webhook_url: str,
    webhook_secret: str,
    allowed_recipients: Sequence[str] = (),
) -> InvitationNotifier:
    if not enabled:
        return DisabledInvitationNotifier()
    return WebhookInvitationNotifier(
        webhook_url,
        webhook_secret,
        allowed_recipients=allowed_recipients,
    )
