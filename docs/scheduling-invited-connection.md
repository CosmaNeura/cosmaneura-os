# Invited-user Scheduling connection

An existing CosmasOS member who has accepted the Scheduling practice invitation
can connect through Settings → Connections → Scheduling. Sign in with the invited
Google account, select the location and default appointment type, review the
practice and practitioner, then confirm. Missing practitioner setup directs the
user to the existing Scheduling setup flow.

The service must have the existing Scheduling Google sign-in configuration plus
`WORKSPACE_SCHEDULING_ENROLLMENT_ENABLED=true` and
`SCHEDULING_ENROLLMENT_PRACTICE_ID` set to the owner-approved canonical practice
UUID. The renderer additionally requires
`VITE_WORKSPACE_SCHEDULING_ENROLLMENT_ENABLED=true`. The receiver requires
`COSMANEURA_SCHEDULING_COMPANION_CONNECTION_ENABLED=true`. All new flags default
off. Apply ordinary OS migration `de316d1b22db` before enabling the feature.

This creates the established SchedulingAccount and encrypted credential together
with an immutable confirmation receipt. It does not grant CosmasOS Box access,
create a Scheduling membership, infer identity from email, or undo administrative
revocation. Current OS authority and receiver membership are checked again when
the user confirms. The native clients reuse their existing Google browser handoff.

If confirmation loses its reply, use **Check saved connection result**. The app
retains the exact command reference in memory and never automatically resubmits
the write. After a full app restart, connection status finds a committed account.
Pending sign-in may be cancelled or expires after ten minutes. A claimed OAuth
code is never exchanged again after an uncertain response. No credential is
returned to or persisted by the renderer.

Disabling enrollment leaves existing connections on the established sign-in path.
An administrator-revoked correspondence requires administrative review. Database
receipts are retained; downgrade is supported only before any enrollment attempts
exist. Do not delete history to downgrade an active installation.

W55 local qualification uses synthetic signed tokens, actual Unix HTTP to the
Scheduling receiver and ordinary PostgreSQL migrations. Real Google service,
native return/device, deployment and distribution acceptance remain separate.
