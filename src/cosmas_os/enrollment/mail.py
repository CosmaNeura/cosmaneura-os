"""Invitation email delivery for CosmaBot enrollment.

Disabled by default. When enabled, posts a structured invite to the operator's
HTTPS mail webhook. Secret values never appear in the payload body beyond the
signed authorization header.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import urllib.error
import urllib.request
from typing import Protocol
from urllib.parse import urlparse


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


class WebhookInvitationNotifier:
    """Operator-owned HTTPS webhook that actually delivers the invitation email."""

    def __init__(self, url: str, secret: str, *, timeout_seconds: float = 8.0):
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Invitation mail webhook must be an exact HTTPS URL.")
        if len(secret) < 32:
            raise ValueError("Invitation mail webhook secret must be at least 32 characters.")
        self._url, self._secret, self._timeout = url, secret, timeout_seconds

    def send_invitation(
        self,
        *,
        to_email: str,
        practice_display_name: str,
        invite_url: str,
        expires_at: str,
        role: str,
    ) -> bool:
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


def build_invitation_notifier(*, enabled: bool, webhook_url: str, webhook_secret: str) -> InvitationNotifier:
    if not enabled:
        return DisabledInvitationNotifier()
    return WebhookInvitationNotifier(webhook_url, webhook_secret)
