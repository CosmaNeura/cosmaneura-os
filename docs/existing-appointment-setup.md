# Existing appointments during provider onboarding

After connecting an existing practice account, a provider can check the selected
date range, review counts, and explicitly connect eligible appointments. The
shared web, Apple and desktop panel works in batches of 25 over at most 31 days.
The start date is inclusive and the Before date is exclusive. Each next batch
requires another check and confirmation. Clinical records remain in Core.

The default-off OS flag is `WORKSPACE_CORE_APPOINTMENT_SETUP_ENABLED`; it requires
the existing authenticated Core connection configuration. The client requires
`VITE_CORE_APPOINTMENT_SETUP_ENABLED=true` and the existing workspace and Core
connection flags. The public hosted examples leave the new flags off.

The existing signed `POST /connections/cosmaneura/read` command route accepts
`appointment_setup_preview` and `appointment_setup_connect`. The OS resolves
the actor and tenant from its current reviewed account, sends a fresh human
bearer only to the pinned Core origin, and rechecks local identity/account
authority after the response. No OS records are written by these two actions.
No new native proxy destination or general write capability is added.

Core must enable `COMPANION_APPOINTMENT_SETUP_ENABLED` for the new version-1
`POST /embed/v1/companion/appointments/connect` receiver. It reuses ordinary
provider access and the reviewed doctor/provider link. A read-only preview
returns counts and a hash of the exact source batch and current correspondence.
Confirmation recomputes that plan under transaction locks and creates only
missing eligible person origins, appointment references and their audit events.
It reuses exact Core patient identifiers and canonical-person origins, without
demographic matching. Revoked, inactive, ambiguous and colliding references
remain for practice review. All source appointments and clinical rows remain.

A changed plan returns 409. An interrupted or timed-out response can follow a
successful Core commit: the app clears the old review and asks the provider to
view appointments or check again. There is no automatic confirmation retry.
After an OS account revocation the response is withheld; a Core transaction
already committed before that revocation remains saved.

Local qualification used ordinary migrations, two real loopback services,
invented signed identities, and desktop/phone browser layouts. It covers
competing confirmation, rollback, commit deadline, stale plan, revoked provider,
lost successful reply, and local account revocation. It does not establish real
Clerk, TLS, Athena, restricted database-role, installed device or release readiness.
This is Core appointment setup; Athena-to-Core patient correspondence remains
separate work.

Disable the Core receiver first to stop new setup writes, then disable the OS
and client controls. Keep created references, origins and audits; disabling the
feature does not undo data. Preserve W42's private-reference-aware readers and
W43's ordinary new-appointment lifecycle. No schema revision is added here.
