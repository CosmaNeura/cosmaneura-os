# Shared identity with separate product permissions

Owner decision: DL-20260927-01. Risk: Tier 2, authentication and saved-state
transition. CosmaBot stays in its own repository, deployment and data boundary.

## Native staging prerequisite

The platform staging identity uses a Clerk development instance. The new
`operational-staging-v1` native identity profile accepts only a matching
development public key/frontend, retains the existing beta app identifiers and
requires explicit synthetic data mode throughout build preparation, composition,
desktop packaging and desktop startup. Production identity validation remains
unchanged. A distinct native Keychain namespace preserves prior credentials and
prevents presenting them to the new staging frontend.

The profile selects the shared default-session contract with an explicitly empty
audience in public configuration. The API and native client require the signed
JWT to omit `aud` entirely, including rejecting null/empty audience claims. The
default production policy remains audience-bound. Shared-session admission is
limited to a development issuer and synthetic staging; existing organization,
Box, binding and active-human authorization remain independent requirements.
No global Core/Clerk claims change is required.

This source increment does not change the installed app, desktop installation
marker, account bindings, organization membership or either live Clerk instance.
It cannot by itself complete the identity transition. An existing incompatible
desktop marker still refuses startup while retaining all local files.

## Account and session transition

1. Read the actual platform instance, verified user, organization configuration
   and session contract. Preserve the existing platform/Scribe authentication.
   Current platform sessions have no custom audience claim; do not globally add
   CosmaBot's audience to make its existing verifier pass. An offline signed
   fixture through the actual Core SDK confirmed its default accepts no audience
   and rejects an added CosmaBot audience. The explicit CosmaBot policy avoids
   changing that shared provider contract.
2. Bind the verified platform subject to the same existing CosmaBot human and
   Box through an explicit, auditable transition. A verified email comparison
   alone is not an account binding. Do not create a replacement owner/practice
   or infer CosmaBot ownership from a platform/Clerk administrator role.
3. Confirm separate authorization: an unbound platform user, wrong organization,
   revoked binding or inactive human remains denied. Core provider/encounter
   grants remain independently required for clinical operations.
4. Prepare an exact installed-state transition that preserves Box/principal
   identity, audit history, encrypted drafts, recordings and pending requests.
   Never delete or reset a populated profile to bypass its identity check.
5. Review the concrete account/configuration change and rollback, then activate
   coordinated web/API/native candidates within the approved staging window.
   Old and new application/session policies must not be silently mixed.

## Acceptance and recovery

Check actual shared sign-in, unchanged private draft namespace, explicit product
grant denial, logout/restart and Mac/iPhone capture-to-reviewed-note operation.
No production or full-Beta acceptance is implied by source checks. The former
Clerk instance and account records remain intact until the reviewed transition
and its recovery have been qualified; disabling a feature does not undo an
identity or installed-state migration.

## Reviewed staging transition tools

`infra/beta/vm/operator/workspace_identity.py` is an operator command, outside the
API image and HTTP routes. Its reviewed JSON manifest names the exact existing
Box, owner, original binding and verified shared subject/organization, a new
binding and transition UUID, membership verification evidence, and a UTC
maintenance deadline no more than 24 hours away. Do not infer these from email.
Run `plan` against the mounted staging runtime before scheduling the switch.
For `apply` or `rollback`, fence incoming traffic and stop API/worker writers;
invoke it as UID 10001 in a one-shot container with the canonical runtime and
credential mounts. The command accepts the action, manifest JSON and
`--confirm-reviewed-staging-maintenance`. Keep credentials out of arguments and
logs. Its transaction rechecks the owner, existing identity and audit evidence.
It refuses active model work or any unrevoked Core/Scheduling correspondence.
Applying adds only the shared binding and an audit event. Rollback deactivates
that binding and records another event; it never deletes the original binding.

`scripts/transition-desktop-identity.mjs` handles the existing synthetic Mac
profile. Its public manifest contains the two validated native identities,
original marker SHA-256, transition UUID and UTC deadline. Quit CosmaBot normally
and retain exclusive control of app launches throughout the operation. The
operator command checks for running CosmaBot apps/helpers and open profile files;
helpers inside the separate Scribe app do not block this operation. It does
not quit a recording or reset the profile. Run Node with `plan|apply|rollback`,
the manifest filename and `--confirm-offline-staging-maintenance`. A private,
durable recovery receipt retains the exact original marker before atomic
replacement. API origin, bundle identifiers, Electron/storage generation and
renderer partition stay fixed; only the identity hash changes. An interrupted
maintenance lock requires inspection before removal, never automatic expiry.
Keep recovery receipts until the complete switch and rollback are accepted.

Both commands are bounded to this synthetic staging transition. They do not
provision Clerk users/organizations, deploy applications, grant clinical access,
or change phone storage. Switch the API, web and native public configuration as
one maintenance operation; restore the old configuration with any rollback.
Local evidence covers database ownership/grant separation and populated-profile
preservation, idempotency, interruption and rollback. Actual shared sign-in and
device acceptance remain separate deployment checks.
