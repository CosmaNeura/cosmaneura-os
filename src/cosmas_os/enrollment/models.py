"""Separate registry metadata: never shares clinical tables, migrations or membership authority."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class EnrollmentBase(DeclarativeBase):
    pass


class Account(EnrollmentBase):
    __tablename__ = "enrollment_accounts"
    __table_args__ = (UniqueConstraint("issuer", "subject", name="uq_enrollment_identity"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    issuer: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(320))
    display_name: Mapped[str] = mapped_column(String(160), default="")
    title: Mapped[str] = mapped_column(String(120), default="")
    revision: Mapped[int] = mapped_column(Integer, default=0)
    active_practice_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Practice(EnrollmentBase):
    __tablename__ = "enrollment_practices"
    __table_args__ = (
        CheckConstraint("human_seats >= 1 AND human_seats <= 1000", name="ck_enrollment_humans"),
        UniqueConstraint("box_id", name="uq_enrollment_box"),
        UniqueConstraint("organization_id", name="uq_enrollment_org"),
        UniqueConstraint("stripe_customer_id", name="uq_enrollment_customer"),
        UniqueConstraint("stripe_subscription_id", name="uq_enrollment_subscription"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("enrollment_accounts.id"))
    legal_name: Mapped[str] = mapped_column(String(160))
    display_name: Mapped[str] = mapped_column(String(160))
    address: Mapped[dict[str, Any]] = mapped_column(JSON)
    administrative_email: Mapped[str] = mapped_column(String(320))
    human_seats: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    covered_entity: Mapped[bool] = mapped_column(Boolean)
    workspace_status: Mapped[str] = mapped_column(String(24), default="pending")
    box_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    organization_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    workspace_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    workspace_proof_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    workspace_api_origin: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_commit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    image_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    subscription_status: Mapped[str] = mapped_column(String(32), default="none")
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    trial_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    billing_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_period_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False)
    payment_failure_invoice_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Membership(EnrollmentBase):
    __tablename__ = "enrollment_memberships"
    __table_args__ = (UniqueConstraint("practice_id", "account_id", name="uq_enrollment_member"),
                     CheckConstraint("role IN ('owner','admin','staff')", name="ck_enrollment_role"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    practice_id: Mapped[str] = mapped_column(ForeignKey("enrollment_practices.id"))
    account_id: Mapped[str] = mapped_column(ForeignKey("enrollment_accounts.id"))
    role: Mapped[str] = mapped_column(String(16))
    can_sign: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    workspace_ready: Mapped[bool] = mapped_column(Boolean, default=False)
    workspace_proof_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Acceptance(EnrollmentBase):
    __tablename__ = "enrollment_baa_acceptances"
    __table_args__ = (UniqueConstraint("practice_id", "doc_id", "version", name="uq_enrollment_baa_execution"),
                     CheckConstraint("doc_id = 'CN-BAA-CUST-CW' AND version = '2.3' AND sha256 = '9bdc110b6b2ffcc9f5e7aee653af499357d2f35dccf43c57d8bbcf70094ed34e'", name="ck_enrollment_baa_identity"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    practice_id: Mapped[str] = mapped_column(ForeignKey("enrollment_practices.id"))
    account_id: Mapped[str] = mapped_column(ForeignKey("enrollment_accounts.id"))
    covered_entity_legal_name: Mapped[str] = mapped_column(String(160))
    signer_subject: Mapped[str] = mapped_column(String(255))
    signer_name: Mapped[str] = mapped_column(String(160))
    signer_title: Mapped[str] = mapped_column(String(120))
    signer_email: Mapped[str] = mapped_column(String(320))
    authority_statement: Mapped[str] = mapped_column(Text)
    doc_id: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(16))
    sha256: Mapped[str] = mapped_column(String(64))
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Command(EnrollmentBase):
    __tablename__ = "enrollment_commands"
    __table_args__ = (UniqueConstraint("account_id", "key", name="uq_enrollment_command_retry"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("enrollment_accounts.id"))
    key: Mapped[str] = mapped_column(String(128))
    operation: Mapped[str] = mapped_column(String(32))
    payload_sha256: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CheckoutAttempt(EnrollmentBase):
    __tablename__ = "enrollment_checkout_attempts"
    __table_args__ = (
        UniqueConstraint("stripe_session_id", name="uq_enrollment_checkout_session"),
        Index("uq_enrollment_live_checkout", "practice_id", unique=True,
              postgresql_where=text("state IN ('pending','open','reconciliation_required')"),
              sqlite_where=text("state IN ('pending','open','reconciliation_required')")),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    practice_id: Mapped[str] = mapped_column(ForeignKey("enrollment_practices.id"), index=True)
    request: Mapped[dict[str, Any]] = mapped_column(JSON)
    request_sha256: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(24), default="pending")
    stripe_session_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hosted_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class StripeInbox(EnrollmentBase):
    __tablename__ = "enrollment_stripe_inbox"
    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(128))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    payload_sha256: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(24), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Invitation(EnrollmentBase):
    __tablename__ = "enrollment_invitations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    practice_id: Mapped[str] = mapped_column(ForeignKey("enrollment_practices.id"), index=True)
    email: Mapped[str] = mapped_column(String(320))
    token_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    role: Mapped[str] = mapped_column(String(16))
    can_sign: Mapped[bool] = mapped_column(Boolean)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_by: Mapped[str | None] = mapped_column(ForeignKey("enrollment_accounts.id"), nullable=True)
