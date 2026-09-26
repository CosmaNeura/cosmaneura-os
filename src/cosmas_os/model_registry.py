"""Complete migrated ORM metadata, independent of application import order.

Schema consumers must import this module instead of relying on API routes to
register models. CompactBase is an experiment with separate migration ownership
and deliberately remains outside this registry.
"""

from cosmas_os import (  # noqa: F401 -- imports register declarative models
    finance_models,
    finance_setup_models,
    google_connection_models,
    inbox_handoff_models,
    inbox_models,
    membership_models,
    microsoft_connection_models,
    models,
    portal_models,
    portal_work_models,
    practice_access_models,
    research_models,
    scheduling_enrollment_models,
    scheduling_login_models,
    vendor_models,
    vendor_retirement_models,
    vendor_setup_models,
)
from cosmas_os.db import Base

metadata = Base.metadata
