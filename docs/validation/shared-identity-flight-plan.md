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
