"""Metadata-only Google callback routing over the existing enrollment commands."""
from __future__ import annotations

import hashlib
import time
from typing import Protocol
from uuid import UUID, uuid4, uuid5

from pydantic import SecretStr
from sqlalchemy import select

from cosmas_os.ports.google_callback_broker import (
    Cancellation,
    GoogleBrokerError,
    GoogleRelayPort,
    Receipt,
    ReceiptCheck,
    Registration,
    Relay,
    Scope,
    broker_key,
    callback_digest,
    encoded,
)

from .admission import AdmissionRequest, derive_runtime_admission_key
from .domain import HumanIdentity, now_utc
from .models import Account, Command, Practice
from .service import EnrollmentService

NAMESPACE = UUID("3dd8e56b-efb3-4a5c-942a-5c9f9ab4151a")
OPERATION = "google_callback"


class GoogleBrokerIdentityPort(Protocol):
    def verify_registered_session(self, subject: str, session_id: str, organization_id: str) -> HumanIdentity: ...


def receipt_fields(value: Scope) -> dict:
    return {name: getattr(value, name) for name in Scope.model_fields}


class GoogleCallbackBroker:
    def __init__(self, service: EnrollmentService, identities: GoogleBrokerIdentityPort, relay: GoogleRelayPort,
                 *, now=time.time):
        self.service, self.identities, self.relay, self.now = service, identities, relay, now

    def key(self, value: Scope) -> str:
        return broker_key(derive_runtime_admission_key(self.service.settings.runtime_admission_secret.get_secret_value(),
            value.practice_id, value.box_id, value.organization_id))

    @staticmethod
    def _registered(row: Command, broker_id: str) -> Receipt:
        receipt = Receipt.model_validate(row.response["receipt"])
        if (row.operation != OPERATION or row.id != broker_id or receipt.broker_id != broker_id
                or str(uuid5(NAMESPACE, receipt.state_sha256)) != broker_id
                or row.payload_sha256 != hashlib.sha256(encoded(receipt)).hexdigest()):
            raise GoogleBrokerError("google_broker_attempt_changed")
        return receipt

    def _admit(self, value: Scope, human: HumanIdentity) -> str:
        settings = self.service.settings
        if (settings.google_broker_errors() or not settings.google_callback_broker_enabled
                or value.client_id != settings.google_callback_client_id
                or value.callback_uri != settings.google_callback_broker_origin + "/connections/google/callback"
                or human.issuer != value.issuer or human.subject != value.subject or not human.session_id):
            raise GoogleBrokerError("google_broker_unavailable")
        with self.service.sessions() as session:
            practice = session.get(Practice, value.practice_id)
            web = "https://" + value.practice_id + ".staging.cosmas.ai"
            api = "https://api." + value.practice_id + ".staging.cosmas.ai"
            if (practice is None or practice.box_id != value.box_id or practice.organization_id != value.organization_id
                    or practice.source_commit != value.source_commit or practice.image_sha256 != value.image_sha256
                    or practice.workspace_url != web + "/chief" or practice.workspace_api_origin != api
                    or not settings.registered_workspace_origin(web, practice.id)):
                raise GoogleBrokerError("google_broker_scope_changed")
        request = AdmissionRequest(practice_id=value.practice_id,
            box_id=value.box_id, organization_id=value.organization_id, issuer=value.issuer, subject=value.subject,
            purpose="workspace", nonce=str(uuid4()), issued_at=int(self.now()),
            token_sha256=hashlib.sha256(b"").hexdigest())
        if value.native_origin is not None:
            request = request.model_copy(update={"native_origin":value.native_origin})
        admission = self.service.runtime_admission(human, request)
        if admission["decision"] != "allow":
            raise GoogleBrokerError("google_broker_access_denied")
        return api

    def register(self, human: HumanIdentity, value: Registration) -> Receipt:
        now = int(self.now())
        if not now < value.expires_at <= now + 600:
            raise GoogleBrokerError("google_broker_attempt_expired")
        self._admit(value, human)
        broker_id = str(uuid5(NAMESPACE, value.state_sha256))
        receipt = Receipt(**receipt_fields(value), broker_id=broker_id, session_id=human.session_id)
        digest = hashlib.sha256(encoded(receipt)).hexdigest()
        with self.service.sessions.begin() as session:
            account = session.scalar(select(Account).where(Account.issuer == human.issuer, Account.subject == human.subject))
            if account is None:
                raise GoogleBrokerError("google_broker_access_denied")
            saved = session.scalar(select(Command).where(Command.id == broker_id).with_for_update())
            if saved:
                if (saved.operation != OPERATION or saved.account_id != account.id or saved.payload_sha256 != digest
                        or saved.response.get("phase") != "registered"):
                    raise GoogleBrokerError("google_broker_attempt_changed")
                return self._registered(saved,broker_id)
            session.add(Command(id=broker_id, account_id=account.id, key="google:" + value.state_sha256,
                operation=OPERATION, payload_sha256=digest, created_at=now_utc(),
                response={"receipt": receipt.model_dump(), "phase": "registered"}))
        return receipt

    def cancel(self, value: Cancellation):
        with self.service.sessions.begin() as session:
            row = session.scalar(select(Command).where(Command.id == value.broker_id).with_for_update())
            if row is None or row.operation != OPERATION:
                raise GoogleBrokerError("google_broker_attempt_missing")
            receipt = self._registered(row, value.broker_id)
            if receipt_fields(receipt) != receipt_fields(value) or receipt.session_id != value.session_id:
                raise GoogleBrokerError("google_broker_attempt_changed")
            row.response = {**row.response, "phase": "canceled"}

    def check(self, value: ReceiptCheck) -> Receipt:
        with self.service.sessions() as session:
            row = session.get(Command,value.broker_id)
            if row is None:
                raise GoogleBrokerError("google_broker_attempt_missing")
            receipt = self._registered(row,value.broker_id)
            if (receipt_fields(receipt) != receipt_fields(value) or receipt.session_id != value.session_id
                    or row.response["phase"] not in {"registered","relaying"}
                    or receipt.expires_at <= int(self.now())):
                raise GoogleBrokerError("google_broker_attempt_changed")
        human = self.identities.verify_registered_session(receipt.subject,receipt.session_id,receipt.organization_id)
        if human.session_id != receipt.session_id:
            raise GoogleBrokerError("google_broker_session_changed")
        self._admit(receipt,human)
        with self.service.sessions() as session:
            row = session.get(Command,value.broker_id)
            if (row is None or self._registered(row,value.broker_id) != receipt
                    or row.response["phase"] not in {"registered","relaying"}):
                raise GoogleBrokerError("google_broker_attempt_changed")
        return receipt

    def callback(self, state: str, code: str | None, denied: bool) -> str:
        state_sha256 = hashlib.sha256(state.encode()).hexdigest()
        broker_id = str(uuid5(NAMESPACE, state_sha256))
        with self.service.sessions() as session:
            row = session.get(Command, broker_id)
            if row is None or row.operation != OPERATION:
                raise GoogleBrokerError("google_broker_attempt_missing")
            receipt = self._registered(row, broker_id)
        if receipt.state_sha256 != state_sha256 or receipt.expires_at <= int(self.now()):
            raise GoogleBrokerError("google_broker_attempt_expired")
        human = self.identities.verify_registered_session(receipt.subject, receipt.session_id, receipt.organization_id)
        if human.session_id != receipt.session_id:
            raise GoogleBrokerError("google_broker_session_changed")
        api = self._admit(receipt, human)
        digest = callback_digest(state, code, denied)
        with self.service.sessions.begin() as session:
            row = session.scalar(select(Command).where(Command.id == broker_id).with_for_update())
            if row is None or self._registered(row, broker_id) != receipt:
                raise GoogleBrokerError("google_broker_attempt_changed")
            prior = row.response
            if prior.get("callback_sha256") not in {None, digest}:
                raise GoogleBrokerError("google_broker_callback_changed")
            phase = prior["phase"]
            if phase in {"complete", "declined", "failed", "canceled"}:
                return "failed" if phase == "canceled" else phase
            now = int(self.now())
            if phase == "relaying" and prior.get("lease_until", 0) > now:
                return "pending"
            nonce = prior.get("relay_nonce") or str(uuid4())
            row.response = {**prior, "phase": "relaying", "callback_sha256": digest,
                "relay_nonce": nonce, "lease_until": now + 45}
        # Authorization code and state exist only in this bounded HTTP call.
        relay = Relay(**receipt_fields(receipt), broker_id=broker_id, session_id=receipt.session_id,
            nonce=nonce, issued_at=int(self.now()), state=SecretStr(state), code=SecretStr(code) if code is not None else None, denied=denied)
        outcome = self.relay.relay(api, relay, self.key(receipt))
        if (outcome.broker_id != broker_id or outcome.nonce != nonce or outcome.callback_sha256 != digest):
            raise GoogleBrokerError("google_broker_reply_changed")
        with self.service.sessions.begin() as session:
            row = session.scalar(select(Command).where(Command.id == broker_id).with_for_update())
            if (row is None or self._registered(row, broker_id) != receipt
                    or row.response.get("callback_sha256") != digest or row.response["phase"] == "canceled"):
                raise GoogleBrokerError("google_broker_attempt_changed")
            row.response = {**row.response, "phase": outcome.outcome if outcome.outcome != "pending" else "relaying",
                "lease_until": int(self.now()) + 3}
        return outcome.outcome
