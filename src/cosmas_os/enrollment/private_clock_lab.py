"""Explicit private Stripe TEST composition; the default API never imports it.

Only business-period eligibility reads provider time. Identity, signatures,
nonces, persisted command dates and canonical billing freshness use wall time.
The operator-owned binding/journal contain references, never API credentials.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import stat
import time
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any, Literal
from urllib.parse import urlparse
from uuid import UUID, uuid5

import httpx
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import JSON, String, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .auth import ClerkEnrollmentVerifier
from .config import EnrollmentSettings
from .domain import BAA_DOC_ID, BAA_SHA256, BAA_VERSION, TRIAL, EnrollmentError, canonical_hash
from .migration import schema_ready
from .models import Acceptance, Account, CheckoutAttempt, Membership, Practice
from .service import EnrollmentService
from .stripe import EVENT_TYPES, StripeCommerce
from .workspace import ProductionWorkspaceConfirmer

CONTRACT = "enrollment-private-stripe-clock.v1"
BOX_NAMESPACE = UUID("f17d7eec-39ee-5d1e-8071-0d94453d91bd")
SNAPSHOT_MAX_AGE_SECONDS = 5


def refused(code: str = "clock_lab_binding_invalid") -> EnrollmentError:
    return EnrollmentError(code, "The private qualification binding is unavailable.", 503)


def unique_json(raw: bytes) -> Any:
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError("duplicate field")
            value[key] = item
        return value
    return json.loads(raw, object_pairs_hook=pairs)


def protected_read(path: Path, limit: int = 32_768) -> bytes:
    if not path.is_absolute() or path.is_symlink():
        raise refused()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.getuid() or info.st_size > limit:
            raise refused()
        raw = os.read(fd, limit + 1)
        if len(raw) > limit:
            raise refused()
        return raw
    finally:
        os.close(fd)


def private_directory(path: Path) -> None:
    info = path.lstat()
    if (not path.is_absolute() or path.resolve() != path or not stat.S_ISDIR(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o700 or info.st_uid != os.getuid()):
        raise refused()


def write_new(path: Path, value: dict[str, Any]) -> None:
    private_directory(path.parent)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        try:
            existing = unique_json(protected_read(path))
        except (ValueError, TypeError):
            raise refused() from None
        if canonical_hash(existing) != canonical_hash(value):
            raise refused() from None
        return
    with os.fdopen(fd, "wb") as out:
        out.write(json.dumps(value, sort_keys=True).encode())
        out.flush()
        os.fsync(out.fileno())


class ClockLabBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    contract_version: Literal["enrollment-private-stripe-clock.v1"] = CONTRACT
    synthetic_only: Literal[True]
    practice_id: str
    box_id: str
    organization_id: str = Field(pattern=r"^org_[A-Za-z0-9]+$")
    owner_subject: str = Field(pattern=r"^user_[A-Za-z0-9]+$")
    issuer: str
    app_origin: str
    api_origin: str
    workspace_url: str
    workspace_api_origin: str
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    image_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    stripe_account_id: str = Field(pattern=r"^acct_[A-Za-z0-9]+$")
    stripe_base_price_id: str = Field(pattern=r"^price_[A-Za-z0-9]+$")
    stripe_additional_price_id: str = Field(pattern=r"^price_[A-Za-z0-9]+$")
    stripe_portal_configuration_id: str = Field(pattern=r"^bpc_[A-Za-z0-9]+$")
    stripe_api_version: Literal["2025-09-30.clover"]
    customer_id: str = Field(pattern=r"^cus_[A-Za-z0-9]+$")
    clock_id: str = Field(pattern=r"^clock_[A-Za-z0-9]+$")
    initial_frozen_time: int = Field(ge=1, le=253402300799)
    journal_host: str
    journal_port: int = Field(ge=1, le=65535)
    journal_database: Literal["cosmabot_enrollment_clock_lab"]

    def __repr__(self) -> str:
        return "ClockLabBinding(<protected scope>)"

    def __str__(self) -> str:
        return repr(self)

    @property
    def sha256(self) -> str:
        return canonical_hash(self.model_dump())

    def check_settings(self, settings: EnrollmentSettings) -> None:
        def origin(value):
            parsed = urlparse(value)
            return (parsed.scheme == "https" and parsed.netloc == parsed.hostname and parsed.path == ""
                    and not parsed.query and not parsed.fragment
                    and bool(parsed.hostname and parsed.hostname.endswith(".staging.cosmas.ai")))
        issuer = urlparse(self.issuer)
        try:
            public_host = base64.b64decode(settings.clerk_publishable_key.removeprefix("pk_test_"), validate=True).decode()
        except (ValueError, UnicodeDecodeError):
            raise refused() from None
        if (settings.data_mode != "synthetic" or settings.stripe_live_mode or settings.production_qualified
                or settings.auth_errors() or settings.billing_errors() or not settings.enabled
                or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*\.clerk\.accounts\.dev", issuer.hostname or "")
                or self.issuer != settings.clerk_issuer or issuer.geturl() != "https://" + (issuer.hostname or "")
                or public_host != (issuer.hostname or "") + "$"
                or any(not origin(x) for x in (self.app_origin, self.api_origin, self.workspace_api_origin))
                or self.app_origin != settings.public_app_origin
                or settings.allowed_origins != [self.app_origin]
                or settings.clerk_authorized_parties != [self.app_origin]
                or urlparse(self.workspace_url).path != "/chief" or urlparse(self.workspace_url).query or urlparse(self.workspace_url).fragment
                or not origin(self.workspace_url.removesuffix("/chief"))
                or settings.allowed_workspace_origins != [self.workspace_url.removesuffix("/chief")]
                or str(UUID(self.practice_id)) != self.practice_id
                or self.box_id != str(uuid5(BOX_NAMESPACE, self.practice_id))
                or any(getattr(self, key) != getattr(settings, key) for key in (
                    "stripe_account_id", "stripe_base_price_id", "stripe_additional_price_id",
                    "stripe_portal_configuration_id", "stripe_api_version"))):
            raise refused()


def binding_value(value) -> ClockLabBinding:
    try:
        return ClockLabBinding.model_validate(value)
    except (ValueError, TypeError):
        raise refused() from None


class ClockStateBase(DeclarativeBase):
    """Private test-lab metadata; never enrollment/clinical migrations."""


class ClockState(ClockStateBase):
    __tablename__ = "private_stripe_clock_journal"
    binding_sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    state: Mapped[dict[str, Any]] = mapped_column(JSON)


class PostgresClockJournal:
    """Dedicated private database with atomic row locks across replicas."""
    def __init__(self, engine, binding: ClockLabBinding):
        self.check_engine(engine, binding)
        self.engine, self.binding = engine, binding
        self.read()

    @staticmethod
    def check_engine(engine, binding: ClockLabBinding):
        if (engine.url.drivername != "postgresql+psycopg" or engine.url.database != "cosmabot_enrollment_clock_lab"
                or engine.url.host != binding.journal_host or (engine.url.port or 5432) != binding.journal_port
                or engine.url.database != binding.journal_database
                or engine.url.host not in ("127.0.0.1", "localhost") and engine.url.query.get("sslmode") != "verify-full"):
            raise refused()

    @classmethod
    def prepare_database(cls, engine, binding: ClockLabBinding) -> PostgresClockJournal:
        cls.check_engine(engine, binding)
        ClockStateBase.metadata.create_all(engine)
        with engine.begin() as connection:
            connection.execute(insert(ClockState).values(binding_sha256=binding.sha256, state={
                "binding_sha256": binding.sha256, "high_water": binding.initial_frozen_time, "pending_target": None,
                "subscription_id": None, "trial_start": None, "trial_end": None})
                .on_conflict_do_nothing(index_elements=[ClockState.binding_sha256]))
        return cls(engine, binding)

    def _state(self, connection):
        row = connection.execute(select(ClockState.state).where(ClockState.binding_sha256 == self.binding.sha256)
                                 .with_for_update()).one_or_none()
        value = dict(row[0]) if row is not None else {}
        if (set(value) != {"binding_sha256", "high_water", "pending_target", "subscription_id", "trial_start", "trial_end"}
                or value["binding_sha256"] != self.binding.sha256
                or type(value["high_water"]) is not int or not self.binding.initial_frozen_time <= value["high_water"] <= 253402300799
                or value["pending_target"] is not None and (type(value["pending_target"]) is not int or value["pending_target"] < value["high_water"])):
            raise refused()
        sub, start, end = (value[k] for k in ("subscription_id", "trial_start", "trial_end"))
        if sub is not None:
            if (not isinstance(sub, str) or not re.fullmatch(r"sub_[A-Za-z0-9]+", sub)
                    or type(start) is not int or type(end) is not int or start < 1 or end - start != int(TRIAL.total_seconds())):
                raise refused()
        elif start is not None or end is not None:
            raise refused()
        return value

    def read(self) -> dict[str, Any]:
        with self.engine.begin() as connection:
            return self._state(connection)

    def _change(self, change):
        with self.engine.begin() as connection:
            value = self._state(connection)
            result = change(value)
            connection.execute(update(ClockState).where(ClockState.binding_sha256 == self.binding.sha256).values(state=value))
            return result

    def observe(self, stamp: int) -> None:
        def change(value):
            if type(stamp) is not int or not value["high_water"] <= stamp <= 253402300799 or value["pending_target"] not in (None, stamp):
                raise refused("clock_lab_unready")
            value.update(high_water=stamp, pending_target=None)
        self._change(change)

    def subscription(self, sub: dict[str, Any]) -> None:
        current = (sub["id"], sub["trial_start"], sub["trial_end"])
        def change(value):
            previous = tuple(value[k] for k in ("subscription_id", "trial_start", "trial_end"))
            if value["subscription_id"] is not None and current != previous:
                raise refused()
            value.update(zip(("subscription_id", "trial_start", "trial_end"), current, strict=True))
        self._change(change)

    def target(self, point: Literal["before", "expiry", "after"]) -> int:
        if point not in ("before", "expiry", "after"):
            raise refused()
        def change(value):
            if value["trial_end"] is None:
                raise refused()
            target = value["trial_end"] + {"before": -1, "expiry": 0, "after": 1}[point]
            if target < value["high_water"] or value["pending_target"] not in (None, target):
                raise refused()
            value["pending_target"] = target
            return target
        return self._change(change)


def registry_scope(binding: ClockLabBinding, sessions: sessionmaker) -> None:
    with sessions() as session:
        practice = session.get(Practice, binding.practice_id)
        owner = session.get(Account, practice.owner_id) if practice else None
        member = session.scalar(select(Membership).where(Membership.practice_id == binding.practice_id,
            Membership.account_id == owner.id, Membership.active.is_(True), Membership.role == "owner")) if owner else None
        baa = session.scalar(select(Acceptance).where(Acceptance.practice_id == binding.practice_id,
            Acceptance.doc_id == BAA_DOC_ID, Acceptance.version == BAA_VERSION, Acceptance.sha256 == BAA_SHA256))
        collision = session.scalar(select(Practice.id).where(Practice.stripe_customer_id == binding.customer_id,
                                                            Practice.id != binding.practice_id))
        if (not practice or not owner or not member or not baa or collision
                or owner.issuer != binding.issuer or owner.subject != binding.owner_subject
                or practice.box_id != binding.box_id or practice.organization_id != binding.organization_id
                or practice.workspace_url != binding.workspace_url or practice.workspace_api_origin != binding.workspace_api_origin
                or practice.source_commit != binding.source_commit or practice.image_sha256 != binding.image_sha256
                or practice.workspace_status not in ("provisioning", "ready")
                or practice.stripe_customer_id not in (None, binding.customer_id)):
            raise refused()


class ClockLabClerkVerifier(ClerkEnrollmentVerifier):
    """The production verifier plus a narrower one-owner/one-Org lab scope."""
    def __init__(self, settings, binding, **ports):
        self.binding = binding
        super().__init__(settings, **ports)

    def _claims(self, token, authorized_parties=None):
        claims = super()._claims(token, authorized_parties)
        compact = claims.get("o")
        orgs = [claims[key] for key in ("org_id",) if key in claims]
        if compact is not None:
            orgs.append(compact.get("id") if isinstance(compact, dict) else None)
        if claims["sub"] != self.binding.owner_subject or any(org != self.binding.organization_id for org in orgs):
            raise EnrollmentError("clock_lab_scope_denied", "Use the bound qualification account.", 403)
        return claims

    def verify(self, token):
        human = super().verify(token)
        self._membership(human.subject, self.binding.organization_id)
        return human

    def verify_scoped(self, token, organization_id, *, authorized_parties=None):
        if organization_id != self.binding.organization_id:
            raise refused()
        return super().verify_scoped(token, organization_id, authorized_parties=authorized_parties)

    def verify_registered_member(self, subject, organization_id):
        if subject != self.binding.owner_subject or organization_id != self.binding.organization_id:
            raise refused()
        return super().verify_registered_member(subject, organization_id)


class ClockLabCommerce(StripeCommerce):
    def __init__(self, settings: EnrollmentSettings, binding: ClockLabBinding, journal: PostgresClockJournal,
                 sessions: sessionmaker, *, client: httpx.Client | None = None):
        binding.check_settings(settings)
        self.binding, self.journal, self.sessions = binding, journal, sessions
        self.service: EnrollmentService | None = None
        self._stamp: int | None = None
        self._observed_at = 0.0
        self.lock = RLock()
        super().__init__(settings, client=client)

    def guard_scope(self) -> None:
        self.binding.check_settings(self.settings)
        registry_scope(self.binding, self.sessions)

    def refresh_clock(self) -> None:
        with self.lock:
            self._stamp = None
            self.guard_scope()
            clock = self._request("GET", "/test_helpers/test_clocks/" + self.binding.clock_id)
            customer = self._request("GET", "/customers/" + self.binding.customer_id)
            if (clock.get("id") != self.binding.clock_id or clock.get("livemode") is not False or clock.get("status") != "ready"
                    or type(clock.get("frozen_time")) is not int
                    or customer.get("id") != self.binding.customer_id or customer.get("livemode") is not False
                    or customer.get("deleted") is True or customer.get("test_clock") != self.binding.clock_id):
                raise refused("clock_lab_unready")
            self.journal.observe(clock["frozen_time"])
            self._stamp, self._observed_at = clock["frozen_time"], time.monotonic()

    def now(self) -> datetime:
        self.refresh_clock()
        with self.lock:
            if self._stamp is None or time.monotonic() - self._observed_at > SNAPSHOT_MAX_AGE_SECONDS:
                raise refused("clock_lab_unready")
            return datetime.fromtimestamp(self._stamp, UTC)

    def validate_configuration(self) -> None:
        self.guard_scope()
        super().validate_configuration()
        self.refresh_clock()

    def attach(self, service: EnrollmentService) -> None:
        if service.settings is not self.settings or service.commerce is not self or service.settings.data_mode != "synthetic":
            raise refused()
        self.service = service
        service._period_time = self
        self.validate_configuration()
        listed = self._request("GET", "/subscriptions?customer=" + self.binding.customer_id + "&status=all&limit=100")
        rows = listed.get("data")
        if not isinstance(rows, list) or listed.get("has_more") is not False or len(rows) > 1:
            raise refused()
        journal = self.journal.read()
        if not rows and journal["subscription_id"] is not None:
            raise refused()
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("id"), str):
                raise refused()
            self.retrieve_subscription(row["id"])

    def create_checkout(self, request, key):
        self.guard_scope()
        if request.get("practice_id") != self.binding.practice_id or request.get("customer_id") not in (None, self.binding.customer_id):
            raise refused()
        return self._checkout(super().create_checkout({**request, "customer_id": self.binding.customer_id}, key))

    def _checkout(self, value):
        if value.get("customer") != self.binding.customer_id or value.get("client_reference_id") != self.binding.practice_id:
            raise refused()
        return value

    def retrieve_checkout(self, session_id):
        self.guard_scope()
        return self._checkout(super().retrieve_checkout(session_id))

    def retrieve_subscription(self, subscription_id):
        self.refresh_clock()
        return self._canonical_subscription(subscription_id)

    def _canonical_subscription(self, subscription_id):
        self.guard_scope()
        value = super().retrieve_subscription(subscription_id)
        if value.get("customer") != self.binding.customer_id or (value.get("metadata") or {}).get("practice_id") != self.binding.practice_id or self.service is None:
            raise refused()
        # Reuse the production canonical offer/trial validator in a transaction
        # that rolls back. Only the normal service persists billing evidence.
        with self.sessions() as session:
            practice = session.get(Practice, self.binding.practice_id)
            attempt = session.get(CheckoutAttempt, (value.get("metadata") or {}).get("attempt_id"))
            if practice is None or attempt is None or attempt.practice_id != practice.id or canonical_hash(attempt.request) != attempt.request_sha256:
                raise refused()
            self.service._apply_subscription(practice, attempt, value)
        self.journal.subscription(value)
        return value

    def retrieve_invoice(self, invoice_id):
        self.guard_scope()
        value = super().retrieve_invoice(invoice_id)
        subscription_id = self.journal.read()["subscription_id"]
        invoice_subscription = value.get("subscription") or (value.get("parent", {}).get("subscription_details", {}).get("subscription"))
        if subscription_id is None or value.get("customer") != self.binding.customer_id or invoice_subscription != subscription_id:
            raise refused()
        return value

    def create_portal(self, customer_id, return_url):
        if customer_id != self.binding.customer_id or return_url != self.binding.app_origin + "/onboarding":
            raise refused()
        return super().create_portal(customer_id, return_url)

    def verify_event(self, raw, signature):
        event = super().verify_event(raw, signature)
        self.guard_scope()
        obj, kind = event["data"]["object"], event["type"]
        if kind not in EVENT_TYPES or obj.get("customer") != self.binding.customer_id:
            raise refused()
        if kind.startswith("checkout.session."):
            self._checkout(obj)
            metadata = obj.get("metadata") or {}
            with self.sessions() as session:
                attempt = session.get(CheckoutAttempt, metadata.get("attempt_id"))
                if metadata.get("practice_id") != self.binding.practice_id or not attempt or attempt.practice_id != self.binding.practice_id:
                    raise refused()
        elif kind.startswith("customer.subscription."):
            if (obj.get("metadata") or {}).get("practice_id") != self.binding.practice_id:
                raise refused()
            self._canonical_subscription(obj["id"])
        elif kind.startswith("invoice."):
            self._canonical_subscription(obj.get("subscription") or obj.get("parent", {}).get("subscription_details", {}).get("subscription", ""))
        return event

    def advance(self, point: Literal["before", "expiry", "after"]) -> dict[str, str]:
        """Trusted operator composition only; no HTTP route/date/customer input."""
        with self.lock:
            self._stamp = None
            self.guard_scope()
            target = self.journal.target(point)
            clock = self._request("GET", "/test_helpers/test_clocks/" + self.binding.clock_id)
            if clock.get("id") != self.binding.clock_id or clock.get("livemode") is not False:
                raise refused()
            if clock.get("status") == "advancing":
                return {"state": "pending", "point": point}
            if clock.get("status") != "ready" or type(clock.get("frozen_time")) is not int or clock["frozen_time"] > target:
                raise refused()
            if clock["frozen_time"] != target:
                self._request("POST", "/test_helpers/test_clocks/" + self.binding.clock_id + "/advance",
                              {"frozen_time": str(target)}, "cosmas-clock-lab:" + self.binding.sha256 + ":" + str(target))
            try:
                self.refresh_clock()
            except EnrollmentError as exc:
                if exc.code != "clock_lab_unready":
                    raise
                return {"state": "pending", "point": point}
            return {"state": "ready", "point": point}


def prepare_clock_binding(settings: EnrollmentSettings, engine, manifest: dict[str, Any], *,
                          binding_path: Path, stripe_client: httpx.Client | None = None,
                          clerk_client: httpx.Client | None = None, jwks_client=None, journal_engine) -> None:
    """Operator-only preparation: canonical TEST/Clerk GETs, no vendor writes."""
    binding = binding_value(manifest)
    binding.check_settings(settings)
    PostgresClockJournal.check_engine(journal_engine, binding)
    if journal_engine.url.database == engine.url.database:
        raise refused()
    sessions = sessionmaker(engine, expire_on_commit=False)
    registry_scope(binding, sessions)
    verifier = ClockLabClerkVerifier(settings, binding, client=clerk_client, jwks_client=jwks_client)
    verifier.verify_registered_member(binding.owner_subject, binding.organization_id)
    commerce = StripeCommerce(settings, client=stripe_client)
    commerce.validate_configuration()
    clock = commerce._request("GET", "/test_helpers/test_clocks/" + binding.clock_id)
    customer = commerce._request("GET", "/customers/" + binding.customer_id)
    subscriptions = commerce._request("GET", "/subscriptions?customer=" + binding.customer_id + "&status=all&limit=100")
    with sessions() as session:
        practice = session.get(Practice, binding.practice_id)
        if practice is None or practice.stripe_subscription_id or practice.trial_started_at:
            raise refused()
    if (clock.get("id") != binding.clock_id or clock.get("livemode") is not False or clock.get("status") != "ready"
            or clock.get("frozen_time") != binding.initial_frozen_time or type(clock.get("frozen_time")) is not int
            or customer.get("id") != binding.customer_id or customer.get("livemode") is not False
            or customer.get("deleted") is True or customer.get("test_clock") != binding.clock_id
            or subscriptions.get("data") != [] or subscriptions.get("has_more") is not False):
        raise refused()
    write_new(binding_path, binding.model_dump())
    PostgresClockJournal.prepare_database(journal_engine, binding)


def create_clock_lab_app(settings: EnrollmentSettings, *, engine, binding_path: Path,
                         stripe_client: httpx.Client | None = None, clerk_client: httpx.Client | None = None,
                         jwks_client=None, workspace_confirmer=None, journal: PostgresClockJournal):
    """Explicit private ASGI factory. No global app or production switch exists."""
    from starlette.concurrency import run_in_threadpool
    from starlette.responses import JSONResponse

    binding = binding_value(unique_json(protected_read(binding_path)))
    binding.check_settings(settings)
    if not schema_ready(engine):
        raise refused()
    if workspace_confirmer is not None and not isinstance(workspace_confirmer, ProductionWorkspaceConfirmer):
        raise refused()
    if not isinstance(journal, PostgresClockJournal) or journal.binding.sha256 != binding.sha256 or journal.engine.url.database == engine.url.database:
        raise refused("clock_lab_durable_journal_required")
    active_journal = journal
    sessions = sessionmaker(engine, expire_on_commit=False)
    registry_scope(binding, sessions)
    verifier = ClockLabClerkVerifier(settings, binding, client=clerk_client, jwks_client=jwks_client)
    verifier.verify_registered_member(binding.owner_subject, binding.organization_id)
    commerce = ClockLabCommerce(settings, binding, active_journal, sessions, client=stripe_client)
    # Import only after rejecting production/unsafe configuration.
    from .api import create_app
    app = create_app(settings, engine=engine, verifier=verifier, commerce=commerce, workspace_confirmer=workspace_confirmer)
    service = app.state.enrollment_service
    if service is None:
        raise refused()
    commerce.attach(service)
    app.state.private_clock_commerce = commerce
    public = {("GET", p) for p in ("/health", "/ready", "/operational-ready", "/enrollment/v1/config")}
    ordinary = {("GET", "/enrollment/v1/" + p) for p in ("status", "practices", "baa/current", "baa/receipt", "quote")}
    ordinary |= {("POST", "/enrollment/v1/" + p) for p in ("select-practice", "checkout", "recover", "portal", "workspace/confirm")}
    admission = ("POST", "/enrollment/v1/runtime/admission")
    webhook = ("POST", "/enrollment/v1/webhooks/stripe")

    @app.middleware("http")
    async def private_scope(request, call_next):
        pair = (request.method, request.url.path)
        try:
            if request.scope.get("query_string") or pair not in public | ordinary | {admission, webhook} and request.method != "OPTIONS":
                raise refused("clock_lab_scope_denied")
            if pair not in public and request.method != "OPTIONS":
                await run_in_threadpool(commerce.guard_scope)
            if pair in ordinary:
                values = request.headers.getlist("authorization")
                if len(values) != 1 or not values[0].startswith("Bearer "):
                    raise EnrollmentError("invalid_identity", "Sign in to continue.", 401)
                human = await run_in_threadpool(verifier.verify, values[0][7:])
                if pair != ("POST", "/enrollment/v1/select-practice"):
                    with sessions() as session:
                        owner = session.scalar(select(Account).where(Account.issuer == binding.issuer, Account.subject == binding.owner_subject))
                        if owner is None or owner.active_practice_id != binding.practice_id:
                            raise refused("clock_lab_scope_denied")
                if pair == ("GET", "/enrollment/v1/practices"):
                    result = await run_in_threadpool(service.practices, human)
                    result["practices"] = [p for p in result["practices"] if p["id"] == binding.practice_id]
                    response = JSONResponse(result)
                else:
                    response = None
            else:
                response = None
            if pair == admission or pair == ("POST", "/enrollment/v1/select-practice") or pair == webhook:
                raw = bytearray()
                async with asyncio.timeout(5):
                    async for chunk in request.stream():
                        raw.extend(chunk)
                        if len(raw) > (128_000 if pair == webhook else 4096):
                            raise refused("clock_lab_scope_denied")
                request._body = bytes(raw)
                if pair != webhook:
                    body = unique_json(bytes(raw))
                    expected = ({"practice_id": binding.practice_id, "box_id": binding.box_id,
                                 "organization_id": binding.organization_id, "issuer": binding.issuer,
                                 "subject": binding.owner_subject} if pair == admission else {"practice_id": binding.practice_id})
                    if not isinstance(body, dict) or any(body.get(k) != v for k, v in expected.items()):
                        raise refused("clock_lab_scope_denied")
            if response is None:
                response = await call_next(request)
        except (EnrollmentError, ValueError, TypeError, TimeoutError, OSError) as exc:
            error = exc if isinstance(exc, EnrollmentError) else refused()
            response = JSONResponse({"detail": {"code": "enrollment_" + error.code,
                                                 "message": error.message}}, status_code=error.status)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        # Direct scope/roster responses bypass the inner CORS middleware.
        # Preserve browser recovery only for the one bound account origin.
        if request.headers.getlist("origin") == [binding.app_origin]:
            response.headers["Access-Control-Allow-Origin"] = binding.app_origin
            vary = [part.strip() for part in response.headers.get("Vary", "").split(",") if part.strip()]
            if not any(part.lower() == "origin" for part in vary):
                vary.append("Origin")
            response.headers["Vary"] = ", ".join(vary)
        return response

    return app
