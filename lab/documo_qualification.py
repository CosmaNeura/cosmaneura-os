"""Documo qualification through the existing private-PDF, approval and fax lab."""

from lab.fax_sandbox import FAX_SCENARIOS, exercise_fax

SCENARIOS = FAX_SCENARIOS["documo"]


def exercise(app, root, scenario):
    return exercise_fax(app, root, scenario, provider="documo")
