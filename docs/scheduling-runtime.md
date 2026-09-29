# Configured Scheduling startup

The host can configure the ordinary ASGI app before serving requests:

```python
from cosmas_os.api.app import app
from cosmas_os.adapters.scheduling_runtime import (
    SchedulingServiceProfile,
    configure_scheduling,
)

configure_scheduling(app, SchedulingServiceProfile(
    origin=installed_scheduling_origin,
    staff_credential=acquire_bound_staff_credential,
))
```

The installed API base must be HTTPS on the standard port, with no credentials,
query or fragment. It may be the service origin or end in exactly `/api` for
Scheduling's shared web/API host; arbitrary paths are rejected. Requests append
their `/v1/...` route to this base without redirects or fallback to another path.
The callable must return SchedulingStaffCredential,
including the exact supplied SchedulingSelection, a Microsoft staff access or
Google staff identity token, and its verified expiry. A token needs at least
30 seconds of remaining validity and no more than one day. The provider owns
identity acquisition and verification of those metadata; the receiver separately
verifies the actual token and current membership. Profile construction is not
proof that credentials or staff access are valid.

The selection includes the distinct Box, owner and Scheduling practice IDs,
practitioner, location, appointment type and reviewed staff actor. It excludes
patient identifiers. A provider must resolve this exact reviewed mapping; it
must not infer identity from an email, silently change accounts or substitute
the workspace Clerk session, a workload token or a Google Calendar access token.
Provider exceptions and invalid, mismatched or expired results are redacted and
stop the call before HTTP. Tokens are reacquired on each request and never cached
or persisted by this composition.

Configuration must happen once before startup. A configured profile requires
the existing authenticated local Scheduling workspace gate. Appointment calls
additionally require the independent appointment gate. Gates are checked both
before and after credential acquisition. Configuration does not change either
gate, create an account, approve an appointment or activate any external service.
Without a profile the existing unavailable response remains. The normal request
identity, current database authorization, immutable approval, receiver conflict
and once-ever operation boundaries are unchanged.

The ordinary application lifespan owns both HTTP clients and settles its
background workers before closing them. Failed startup and sibling cleanup
failures also release the owned clients. A stopped or disabled runtime cannot
acquire another credential. Host-owned credential storage and refresh remain the
responsibility of the supplied provider, including their own shutdown behavior.

This source supports configured local qualification. Real staff login/token
acquisition, provider and calendar acceptance, authorized beta hosting and native
device acceptance remain separate unfinished work. The default remains closed.
