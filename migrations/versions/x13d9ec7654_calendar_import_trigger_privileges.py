"""Keep source custody helpers private behind scoped trigger guards."""

from alembic import op

revision = "x13d9ec7654"
down_revision = "w02c8db6543"
branch_labels = None
depends_on = None


def upgrade():
    # These existing NEW-row guards use public-qualified relations/helpers and
    # validate exact owner/workspace/source custody. The prepared application
    # role may write the tables, but still executes only its seven pure
    # validators directly. As with the Google-source guards, run this private
    # trigger closure as its migration owner, with no caller-controlled path.
    # The calendar, EHR and Microsoft deferred entry guards also run on
    # ordinary Chief and fax entries; PostgreSQL checks helper privileges while
    # planning the IF expression, even when the entry has a different kind.
    op.execute("""
ALTER FUNCTION public.guard_microsoft_message_entry() SECURITY DEFINER SET search_path=pg_catalog;
ALTER FUNCTION public.guard_ehr_read_entry() SECURITY DEFINER SET search_path=pg_catalog;
ALTER FUNCTION public.guard_calendar_import_request() SECURITY DEFINER SET search_path=pg_catalog;
ALTER FUNCTION public.guard_calendar_import_snapshot() SECURITY DEFINER SET search_path=pg_catalog;
ALTER FUNCTION public.guard_calendar_import_review() SECURITY DEFINER SET search_path=pg_catalog;
ALTER FUNCTION public.guard_calendar_import_entry() SECURITY DEFINER SET search_path=pg_catalog;
ALTER FUNCTION public.guard_calendar_import_revocation() SECURITY DEFINER SET search_path=pg_catalog;
REVOKE ALL ON FUNCTION public.guard_microsoft_message_entry(), public.guard_ehr_read_entry(),
 public.guard_calendar_import_request(), public.guard_calendar_import_snapshot(),
 public.guard_calendar_import_review(), public.guard_calendar_import_entry(),
 public.guard_calendar_import_revocation() FROM PUBLIC;
""")


def downgrade():
    raise RuntimeError("Retain private source trigger custody under the prepared runtime role")
