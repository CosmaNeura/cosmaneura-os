# Clerk setup and identity migration plan

Status: **DEVELOPMENT STRUCTURE CREATED / PRODUCTION DOMAIN BLOCKED**
Last reviewed: 2026-09-03

This plan keeps Cosmas OS identity independent from MyCatholicDoctor while
allowing selected people to enroll in both products. `DL-20260903-05`
authorized and recorded the separate development application and Beta Lab
Organization only. It does not authorize Track A access, credential handling,
invitations, or user-data transfer.

Current non-secret state: the Cosmas OS development instance is B2B,
email-verification-code, invite-only, Organization membership is required,
users cannot create Organizations, and the session token includes audience
`cosmas-os-beta-api`. The zero-member Cosmas Beta Lab Organization exists. The
production instance is not created because Clerk requires the exact hosted
application domain; no placeholder domain was supplied. The optional custom-
domain path uses two workload plans so Azure can expose the app-specific DNS
verification value before Terraform attempts the binding.

## Recommended topology

1. Create a separate Clerk application named **Cosmas OS**. Do not reuse the
   MyCatholicDoctor application, keys, sessions, webhooks, or custom domain.
2. Use the Cosmas OS Development instance only for local accounts and invented
   data. Use its Production instance for external beta users from the first
   beta invitation; Clerk does not transfer users from Development to
   Production.
3. Give the production instance a dedicated Cosmas OS domain and exact HTTPS
   application origin. Do not allow wildcard or preview origins.
4. Disable open self-signup for D3. A named human creates each Organization
   and sends reviewed invitations. Require verified email and MFA under the
   accepted security policy.
5. For the approved first slice, create one synthetic-only **Cosmas Beta Lab**
   Organization and map it to exactly one Cosmas `box_id`. Never derive
   authority from email domain or public metadata.
6. Later, create a separate Organization and Box for each approved legal
   practice. Never mix Beta Lab users or invented data into a clinic Box.

Each D3 deployment is dedicated to one Organization/Box. Supporting more than
one Organization in a deployment remains a later packing and tenancy decision,
not an invitation shortcut.

## Recommended first launch

Use one Cosmas OS Production application with Organizations enabled, then keep
the first two cohorts distinct:

| Person | Cosmas enrollment | Organization / Box |
|---|---|---|
| Outside usability tester | Invite directly to Cosmas OS | Synthetic-only `Cosmas Beta Lab`; no clinic data |
| Existing MyCatholicDoctor beta user joining the first lab | Re-invite to Cosmas OS with the same verified email | Synthetic-only `Cosmas Beta Lab`; no Track A account or clinic data is transferred |
| Beta Lab tester later joining a clinic | Keep the existing Cosmas user, add reviewed clinic membership | New clinic Organization/Box binding; select that Organization before obtaining a token |
| Later approved bulk cohort | Human-operated export/import | Preserve the approved source ID as lineage; create a reviewed Cosmas binding |

A user can belong to more than one Clerk Organization, but a single D3
deployment accepts exactly one configured Organization and Box. Do not point a
clinic deployment at the Beta Lab Organization or use a Clerk role to bypass
the Cosmas binding.

## Human Clerk console checklist

1. The separate **Cosmas OS** development application now exists in the
   company-owned Clerk account. Activate its Production instance only after the
   exact hosted application domain exists, and before inviting anyone.
2. Configure a dedicated Cosmas sign-in domain, exact HTTPS application origin,
   and exact redirect URLs. Do not add wildcards or MyCatholicDoctor origins.
3. Enable Organizations and restricted/invitation-only enrollment. Require a
   verified email and the approved MFA method; do not use email-domain matching
   as authorization.
4. Create the synthetic-only **Cosmas Beta Lab** Organization for unaffiliated
   testers. Create a separate Organization only when a real practice and Box
   have been approved.
5. Add the custom session-token claim `aud: "cosmas-os-beta-api"` (or another
   human-approved exact audience) and keep all clinic/patient data out of token
   claims and Clerk metadata.
6. Invite the first owner through the Clerk Dashboard. A human then records the
   resulting user subject, Organization ID, issuer, and matching Cosmas Box in
   the protected bootstrap manifest outside this repository.
7. Inject runtime configuration through the approved secret/configuration path.
   Do not commit Clerk values. Token verification uses the public JWKS and does
   not require a Clerk Secret Key; keep any future invitation API or webhook
   secrets in Key Vault.
8. Test sign-in, Organization switching, denied Org access, offboarding, and
   session revocation with invented data before any clinic-data authorization.

If a custom web hostname is desired, follow the staged sequence in
[`WEB_RELEASE.md`](WEB_RELEASE.md): create the web app with the selected custom
origin but the DNS-ready gate off, publish and verify the exact CNAME and
`asuid` TXT records in Cloudflare, update Clerk with the exact custom HTTPS
origin/redirects, and only then enable the binding gate. Do not admit testers
during the unbound stage. This repository does not manage Cloudflare. The
existing `app.cosmaneura.com`, `staging-app.cosmaneura.com`,
`chat.cosmaneura.com`, and `staging-chat.cosmaneura.com` hostnames are
explicitly excluded from the D3 binding input and must remain untouched.

## Additional tester enrollment and offboarding

The first owner is created by the protected `bootstrap-beta-identity` deploy
step. Every later identity change is initiated through an authenticated
owner-only API action; a deployment operator cannot impersonate an owner by
naming one in a file.

- `POST /admin/identities/bind` creates a non-owner human and exact Clerk
  subject binding.
- `GET /admin/identities` returns the privacy-minimized roster needed by the
  owner screen; it exposes no email address, token, Box ID, or internal
  principal ID.
- `POST /admin/identities/deactivate` disables the binding and, when it is the
  last active identity, the human principal.
- `POST /admin/identities/reactivate` explicitly restores an unchanged,
  non-tombstoned member.
- `POST /admin/owner/transfer` atomically transfers ownership to an already
  active, bound human before the prior owner's identity can be removed.

Each body supplies the target `clerk_subject` and a privacy-minimized opaque
`evidence_ref`; bind also supplies a display name. The authenticated bearer
token supplies the acting owner, Organization, and Box. Each mutation records
the actual actor/approver, evidence reference, and canonical request digest.
No endpoint accepts a caller-selected Organization, Box, or owner identity.

The beta web app now exposes these operations through an owner-only **Manage
access** screen. It requires an opaque evidence reference, confirms destructive
deactivation and ownership transfer, and derives the acting owner,
Organization, and Box exclusively from the authenticated session. Do not
perform direct database edits or treat a deploy operator as the owner. A human
must still remove the matching Clerk Organization membership or revoke its
sessions; the inactive Cosmas binding is the immediate application deny gate.

## Token and authority contract

The browser must call Clerk `getToken()` for the currently active Organization
and send that token in the `Authorization: Bearer` header. It must not send a
caller-selected Box or principal ID. This avoids the cross-tab active-Org risk
of relying on the shared session cookie alone.

Cosmas validates:

- the exact production issuer and JWKS origin;
- RS256 signature, key ID, expiry, issued-at, not-before, session, and subject;
- a custom `aud` claim equal to the dedicated Cosmas API audience;
- `azp` equal to an approved exact web origin;
- the active Clerk Organization claim `o.id` (or the legacy equivalent, but
  never conflicting forms); and
- an active, human-reviewed `issuer + subject + organization_id` binding to an
  active human principal in the configured Box.

Configure the Cosmas Clerk session token with only the extra claim needed by
the current backend, for example:

```json
{
  "aud": "cosmas-os-beta-api"
}
```

Keep clinic and patient data out of Clerk metadata and JWT claims. Clerk roles
may control UI visibility, but they do not make a user a Cosmas owner or
approver; the Cosmas database remains authoritative.

## Porting selected MyCatholicDoctor users

### Recommended for the first beta: re-invite

1. A human selects and approves the cohort without giving a coding agent the
   MyCatholicDoctor user export or credentials.
2. A human invites each person to the correct Cosmas Organization.
3. The person accepts, verifies identity, enrolls MFA, and signs in to the
   Cosmas domain. Existing MyCatholicDoctor sessions are neither shared nor
   accepted.
4. The authenticated Cosmas Box owner reviews the new Clerk subject and binds
   it through the owner-only identity administration path.
5. Test allowed, denied, inactive, wrong-Organization, and offboarding cases
   with synthetic data before enabling any clinic data.

This deliberately gives the person a new Cosmas Clerk subject. Email is an
invitation/contact attribute, not the authorization key.

### Later alternative: password-preserving export/import

Clerk documents a JSON/CSV migration tool and Backend API import path that can
accept compatible password hashes and preserve a legacy identifier as
`external_id`. It also warns that active sessions end and that export/import is
a point-in-time consistency event.

Using that path from MyCatholicDoctor would require separate Track A authority,
an approved data-handling location, a reviewed cohort and field allowlist,
duplicate/conflict rules, rate-limit handling, audit evidence, and a human-run
cutover. No export, password hash, email list, API key, or migration artifact
may enter this repository or an agent conversation. D3 approval alone does not
authorize that Track A operation.

## Human inputs still required

- Cosmas OS production domain and exact web origin (**current blocker**).
- Cosmas OS Clerk production issuer and JWKS URL.
- The API audience string.
- First Beta Lab Clerk Organization ID and dedicated synthetic Box UUID.
- Invitation policy, MFA requirement, and initial owner/approver.
- Re-invite versus later bulk migration decision.
- Clerk plan/service-eligibility review and evidence reference; any applicable
  BAA review is additionally required for `authorized_beta`.
- Joiner, role-change, offboarding, session-revocation, and break-glass owners.

## Acceptance tests before live beta

- A valid invited user in the active approved Org reaches only its Box.
- Wrong Org, no active Org, wrong audience/origin/issuer, missing binding,
  inactive principal, and caller-supplied identity headers all fail closed.
- Organization switching obtains a fresh bearer token and cannot leak data
  between tabs.
- Removing Org membership or disabling the Cosmas binding revokes access within
  the accepted maximum window.
- A Clerk signing-key rotation succeeds without accepting an unknown key or
  allowing unknown-key requests to exhaust the API.
- Audit records identify the Cosmas principal and decision without logging JWTs,
  email addresses, or other identity payloads.

References: [Clerk Organizations](https://clerk.com/docs/guides/organizations/overview),
[session-token claims](https://clerk.com/docs/guides/sessions/session-tokens),
[session-token customization](https://clerk.com/docs/guides/sessions/customize-session-tokens),
and [migration guidance](https://clerk.com/docs/guides/development/migrating/overview).
