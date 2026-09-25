"""Ordinary app startup configuration for hosted Scheduling sign-in."""

from contextlib import contextmanager

from cosmas_os.adapters.scheduling_enrollment import SchedulingEnrollmentLogin
from cosmas_os.adapters.scheduling_runtime import SchedulingServiceProfile, configure_scheduling


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
        yield
    finally:
        app.state.scheduling_google_login = None
        if profile is not None and getattr(app.state, "scheduling_profile", None) is profile:
            app.state.scheduling_profile = None
        if login is not None:
            login.close()
