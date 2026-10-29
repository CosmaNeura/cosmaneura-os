"""Synthetic laboratory bridge retaining the independently verified visit proof."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from cosmas_os.adapters.elation_lab_read import (
    ElationLabError,
    ElationLabReader,
    ElationLabScope,
    ElationReportPage,
    identifier,
    validate_page,
)
from cosmas_os.adapters.elation_read import (
    ElationAppointment,
    ElationPatient,
    ElationReadResult,
)
from cosmas_os.adapters.elation_read_runtime import SyntheticElationReads
from cosmas_os.application.elation_lab_snapshot import (
    ElationLabReviewSnapshot,
    prepare_lab_review,
)

IdentityCheck = Callable[[ElationAppointment, ElationPatient], bool]


def _authority(port, scope, authorize):
    if (
        type(port) is not SyntheticElationReads
        or type(scope) is not ElationLabScope
        or not callable(authorize)
    ):
        raise ElationLabError("invalid_scope")

    def allowed(selected=scope):
        return (
            selected == scope
            and port.labs_available(scope.connection_scope)
            and authorize() is True
            and port.labs_available(scope.connection_scope)
        )

    if not allowed():
        raise ElationLabError("access_denied")
    return allowed


def _visit(port, scope, appointment_id, allowed, verify_identity):
    identifier(appointment_id)
    if not callable(verify_identity):
        raise ElationLabError("invalid_scope")
    appointment, patient = port.visit(
        scope.connection_scope, appointment_id, scope.patient_id, authorize=allowed
    )
    if (
        appointment.scope != scope.connection_scope
        or patient.scope != scope.connection_scope
        or len(appointment.rows) != 1
        or len(patient.rows) != 1
        or type(appointment.rows[0]) is not ElationAppointment
        or type(patient.rows[0]) is not ElationPatient
        or verify_identity(appointment.rows[0], patient.rows[0]) is not True
        or not allowed()
    ):
        raise ElationLabError("record_unavailable")
    return appointment, patient


def lab_reports(
    port: SyntheticElationReads,
    scope: ElationLabScope,
    appointment_id: int,
    *,
    authorize: Callable[[], bool],
    verify_identity: IdentityCheck,
) -> tuple[ElationReadResult, ElationReadResult, ElationReportPage]:
    allowed = _authority(port, scope, authorize)
    appointment, patient = _visit(port, scope, appointment_id, allowed, verify_identity)
    reader = ElationLabReader(
        scope,
        port._transport,
        enabled=lambda: port.labs_available(scope.connection_scope),
        authorize=allowed,
    )
    page = reader.list_reports()
    if not allowed():
        raise ElationLabError("access_denied")
    return appointment, patient, page


def lab_report(
    port: SyntheticElationReads,
    scope: ElationLabScope,
    appointment_id: int,
    page: ElationReportPage,
    report_id: int,
    *,
    expected_candidates_sha256: str,
    authorize: Callable[[], bool],
    verify_identity: IdentityCheck,
) -> tuple[ElationReadResult, ElationReadResult, ElationLabReviewSnapshot]:
    allowed = _authority(port, scope, authorize)
    identifier(report_id)
    validate_page(page, scope, expected_candidates_sha256)
    if not timedelta(seconds=-30) <= datetime.now(UTC) - page.observed_at <= timedelta(minutes=30):
        raise ElationLabError("selection_expired")
    if not any(row.report_id == report_id for row in page.candidates):
        raise ElationLabError("record_unavailable")
    appointment, patient = _visit(port, scope, appointment_id, allowed, verify_identity)
    reader = ElationLabReader(
        scope,
        port._transport,
        enabled=lambda: port.labs_available(scope.connection_scope),
        authorize=allowed,
    )
    observed = reader.read_report(
        page, report_id, expected_candidates_sha256=expected_candidates_sha256
    )
    prepared = prepare_lab_review(
        observed,
        expected_scope=scope,
        expected_source_sha256=observed.source_sha256,
        expected_candidates_sha256=expected_candidates_sha256,
        expected_report_id=report_id,
        authorize_read=allowed,
    )
    if not allowed():
        raise ElationLabError("access_denied")
    return appointment, patient, prepared
