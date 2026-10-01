"""SRFax qualification inside the existing persistent synthetic fax laboratory."""

from lab.fax_sandbox import FAX_SCENARIOS, exercise_fax
from lab.store import LabError

SCENARIOS = tuple(dict.fromkeys((*FAX_SCENARIOS["srfax"], "expired_credentials", "malformed_status", "contradictory_error")))


def exercise(app, root, scenario):
    if scenario not in SCENARIOS:
        raise LabError("unknown_srfax_qualification_scenario")
    return exercise_fax(app, root, scenario, provider="srfax")
