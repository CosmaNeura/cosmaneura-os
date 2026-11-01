"""Real PostgreSQL constraints/locks using an isolated invented enrollment database."""
from concurrent.futures import ThreadPoolExecutor
from os import environ
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from cosmas_os.enrollment.domain import BAA_DOC_ID, BAA_SHA256, BAA_VERSION, HumanIdentity
from cosmas_os.enrollment.migration import upgrade
from cosmas_os.enrollment.models import Acceptance, CheckoutAttempt, Practice
from cosmas_os.enrollment.service import EnrollmentService
from cosmas_os.enrollment.synthetic import SyntheticCommerce, synthetic_settings

URL = environ.get("ENROLLMENT_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not URL, reason="Dedicated PostgreSQL rehearsal URL was not provided")


def test_postgres_receipts_locks_checkout_retry_and_constraints():
    engine = create_engine(URL, pool_pre_ping=True)
    upgrade(engine)
    settings = synthetic_settings()
    commerce = SyntheticCommerce(settings)
    sessions = sessionmaker(engine, expire_on_commit=False)
    service = EnrollmentService(sessions, settings, commerce)
    owner = HumanIdentity(settings.clerk_issuer, "user_pg_example", "sess_pg_example", "owner@example.invalid", "Example Owner")
    service.status(owner)
    state = service.profile(owner, "profile-pg", {"expected_revision": 0, "display_name": "Example Owner", "title": "Owner"})
    state = service.practice(owner, "practice-pg", {"expected_revision": state["revision"], "legal_name": "Postgres Example Practice LLC",
        "display_name": "Postgres Example", "address_line1": "123 Example Road", "address_line2": "", "city": "Example City",
        "region": "NY", "postal_code": "10001", "country": "US", "administrative_email": "office@example.invalid",
        "human_seats": 10, "covered_entity": True})
    state = service.accept(owner, "accept-pg", {"expected_revision": state["revision"], "doc_id": BAA_DOC_ID, "version": BAA_VERSION,
        "sha256": BAA_SHA256, "signature_name": "Example Owner", "signature_title": "Owner", "authority_confirmed": True, "accepted": True})
    service.record_workspace(state["practice"]["id"], box_id=str(uuid4()), organization_id="org_postgresexample",
                             url="https://app.example.invalid/chief", proof_sha256="a" * 64)
    body = {"expected_revision": service.status(owner)["revision"]}
    # Same stable operation races across two sessions. PostgreSQL row locking
    # serializes its freeze and both requests dispatch one provider key.
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: service.checkout(owner, "checkout-pg", body), range(2)))
    assert all(r["status"] == "open" for r in results)
    assert commerce.create_count == 1
    checkout = next(iter(commerce.sessions.values()))
    commerce.complete(checkout["id"])
    raw, signature = commerce.signed_event("checkout.session.completed", checkout, "evt_postgres_example")
    with ThreadPoolExecutor(max_workers=2) as pool:
        acknowledged = list(pool.map(lambda _: service.ingest(raw, signature), range(2)))
    assert acknowledged == [True, True]
    assert service.reconcile_pending()["processed"] == 1
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(CheckoutAttempt)) == 1
        assert session.scalar(select(func.count()).select_from(Acceptance)) == 1
        with pytest.raises(DBAPIError):
            session.execute(text("UPDATE enrollment_baa_acceptances SET signer_name='Rewritten'"))
        session.rollback()
        with pytest.raises(DBAPIError):
            session.execute(text("DELETE FROM enrollment_baa_acceptances"))
        session.rollback()
        with pytest.raises(DBAPIError):
            session.execute(text("UPDATE enrollment_practices SET human_seats=0"))
        session.rollback()
        practice = session.scalar(select(Practice))
        assert practice is not None
        assert practice.human_seats == 10
    engine.dispose()
