# Practice access in the hosted beta

An invited teammate signs in, chooses the configured Clerk organization, and
requests practice access using their name. The app shows a matching code. The
practice owner opens **Settings → Practice access**, matches the supplied name
and code with that teammate, and approves or declines the exact request. Approval
connects that account as an OS practice member. The waiting app checks every
15 seconds while visible and also provides **Check access**.

Names are requester-supplied, not verified names. Matching codes are identifying
aids, not passwords. No raw Clerk identifiers, credentials, or patient data are
displayed in this flow. It does not send invitations or email. Existing Scheduling
invitation acceptance remains separate; Core clinical permissions and outside
account connections retain their existing setup. Athena remains read-only.

Existing active members enter the workspace directly. Existing revoked or remapped
accounts cannot self-enroll or be reactivated by approval. Only the current Box
owner can approve; new requests never grant owner status. Requests expire after
seven days. Each account may create at most five requests per day; each practice
has at most 100 pending requests. A teammate can cancel their own pending request
and then request again. Following an interrupted submission, **Check access**
recovers the server status before another submission. Following an interrupted
owner decision, **Recover approval/decline** resends the exact reviewed decision.
Leaving the app does not cancel a server operation; the next request list reports
pending requests only and does not assert the outcome of an absent request.

## Installation and transport

This is part of every hosted workspace profile, including hosted synthetic
qualification. Local non-hosted proof modes retain their existing entry path.
Install the current OS image and apply the normal reviewed migration chain through
`f72b834c1e90` before installing this client. The additive migration creates
`practice_access_requests`; its downgrade refuses to erase retained request
history. Existing Clerk issuer, audience, organization, dedicated Box, and hosted
workspace configuration are reused. No new secret or provider registration is
required. Existing owner provisioning remains necessary.

The five exact routes are GET `/practice-access`, POST `/practice-access/request`,
POST `/practice-access/cancel`, GET `/practice-access/requests`, and POST
`/practice-access/decide`, all with `X-Cosmas-Practice-Access-Contract: 1` and a fresh
authenticated session. The desktop proxy admits only these method/path pairs,
with 4 KiB request, 128 KiB response, and 15-second limits. Apple retains the
Scribe-based native token bridge and normal WKWebView fetch, with the same closed
client contract and stale-session fence. No generic admin route is enabled.

The backend binds verified JWT subject and organization itself. It records an
immutable request digest and applies the owner's exact decision through the
existing locked identity-binding writer in one transaction. Retries do not repeat
the grant. Authority, cancellation, expiry, concurrency, stale owner state and
request changes have local PostgreSQL qualification. Local UI/transport checks
do not establish actual device, identity-service, or deployment acceptance.

## Connected member access

In **Settings → Practice access → Manage connected members**, the current owner
can review the member roster and pause or restore an existing account's CosmasOS
access. The roster includes the owner as read-only and paginates after 100
accounts. Match the stored name and account code, then explicitly confirm the
selected pause or restore. A review expires after ten minutes and becomes stale
when the binding, person, or relevant identity audit history changes.

Pausing disables this account's binding. The existing identity writer disables
its principal when no other active binding remains. Saved private work is
retained; restore is a separate deliberate owner action. It neither grants owner
status nor restores tombstoned accounts. It does not change direct access to
outside services, Core clinical permissions, or Scheduling permissions. A new
join request still cannot bypass revocation or reactivate an account.

An interrupted change keeps **Recover access change** available. Recovery returns
an immutable historical receipt, then refreshes the current roster. If the owner
has since changed access again, replay does not repeat the earlier change. The
receipt identifies the account and recording time; current state is displayed
separately. Closing the app does not cancel a server-side access change. Reopen
member management to check current access before reviewing another change.

The additional exact POST paths are `/practice-access/members` (body containing
`after_id`, UUID or null) and `/practice-access/member-change`. They use the same
contract header, byte bounds, native custody and deadline as onboarding. The
reviewed command contains an idempotency UUID, opaque member UUID, action, review
time/digest and explicit confirmation. Scope and actual identity remain verified
server-side. The existing AuditEvent table stores the receipt atomically with
the existing owner writer; no additional migration or provider secret is needed.
