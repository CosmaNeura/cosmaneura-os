"""Ordinary app startup configuration for hosted Scheduling sign-in."""

from contextlib import contextmanager

from cosmas_os.adapters.scheduling_enrollment import SchedulingEnrollmentLogin
from cosmas_os.adapters.scheduling_runtime import SchedulingServiceProfile, configure_scheduling
from cosmas_os.application.scheduling_patient_setup import install_binding_reader


@contextmanager
def scheduling_login_lifespan(app, settings, sessions):
    login = None
    profile = None
    try:
        if settings.workspace_scheduling_login_enabled:
            if getattr(app.state, "scheduling_profile", None) is not None:
                raise ValueError("Choose one installed Scheduling credential source")
            login = SchedulingEnrollmentLogin(settings, sessions)
            profile = SchedulingServiceProfile(
                origin=login.origin, staff_credential=login.credential
            )
            configure_scheduling(app, profile)
        app.state.scheduling_google_login = login
        with install_binding_reader(login.patient_setup_binding if login is not None else None):
            yield
    finally:
        app.state.scheduling_google_login = None
        if profile is not None and getattr(app.state, "scheduling_profile", None) is profile:
            app.state.scheduling_profile = None
        if login is not None:
            login.close()
