"""Real account activation and scope validation for the patient-free fax directory."""

from sqlalchemy import event
from tests.integration.test_vendor_settings import (
    ON,
    account,
    account_request,
    activate,
    call,
    command,
)
from tests.integration.test_vendor_settings import (
    setup_case as setup_case,
)
from tests.integration.test_vendor_work import gates as gates
from tests.integration.test_vendor_work import vendor_case as vendor_case

from cosmas_os.application import vendor_readiness as readiness
from cosmas_os.application import vendor_settings as setup


def test_real_review_activation_disable_and_directory_never_reads_recipients(session, setup_case):
    c = setup_case
    installed = c["installed"]
    pending = call(session, c, setup.propose, "propose_account", account_request(c, "srfax"), installed, policy=ON)
    active = account(session, c, "documo")
    statements = []

    def observe(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    connection = session.connection()
    event.listen(connection, "before_cursor_execute", observe)
    try:
        result = readiness.readiness(session, c["box"], c["actor"], installed, policy=ON)
    finally:
        event.remove(connection, "before_cursor_execute", observe)
    providers = {row["id"]: row for row in result["providers"]}
    assert providers["srfax"]["review_required_accounts"] == 1
    assert providers["documo"]["prepare_enabled_accounts"] == 1
    assert not any("patient_links" in sql or "vendor_correspondence_versions" in sql for sql in statements)
    assert not any(sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for sql in statements)
    activate(session, c, pending)
    command(session, c, active, "disable")
    providers = {row["id"]: row for row in readiness.readiness(session, c["box"], c["actor"], installed, policy=ON)["providers"]}
    assert providers["srfax"]["prepare_enabled_accounts"] == 1
    assert providers["documo"]["active_accounts"] == 0
    assert providers["documo"]["unavailable_accounts"] == 1
