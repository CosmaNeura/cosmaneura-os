"""Run the enrollment billing inbox sweep from a private scheduler/worker."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .config import EnrollmentSettings
from .migration import schema_ready
from .service import EnrollmentService
from .stripe import StripeCommerce


def main():
    settings = EnrollmentSettings()
    if settings.billing_errors():
        raise SystemExit("Enrollment Stripe configuration is incomplete")
    engine = create_engine(settings.database_url.get_secret_value(), pool_pre_ping=True)
    if not schema_ready(engine):
        raise SystemExit("Enrollment schema is unavailable")
    commerce = StripeCommerce(settings)
    commerce.validate_configuration()
    service = EnrollmentService(sessionmaker(engine, expire_on_commit=False), settings, commerce)
    print({"events": service.reconcile_pending(), "subscriptions": service.reconcile_subscriptions()})


if __name__ == "__main__":
    main()
