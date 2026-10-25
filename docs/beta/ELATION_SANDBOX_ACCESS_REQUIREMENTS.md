# Elation sandbox access packet

Prepared October 25, 2026 for **CosmaBot**. Status: requirements prepared;
request **not sent**; sandbox **not provisioned**. The integrated local fixture
passes, but the application still accepts only invented credentials and an
in-process mock transport. No vendor qualification is claimed.

## Start here

Use Elation's [developer sandbox / partnership form](https://www.elationhealth.com/contact-us/developer-sandbox-partnership/)
as a prospective integration partner. The initial request is for **Elation
APIv2 / REST**, a private test practice, and appointment/patient reads using
entirely invented data. Elation advertises a free sandbox without an EHR
subscription on its [Core Developer page](https://help.elationhealth.com/core-developer).
Its [FAQ](https://help.elationhealth.com/core-developer-faq) says practices adopting
a vendor-built integration use that vendor's partner agreement and do not need
Core Developer. CosmaBot's partner approval and fees still need confirmation.

The form currently asks for the following. Placeholders are intentionally
unfilled; company branding does not establish a legal contracting entity.

| Form field | Prepared answer or information needed |
| --- | --- |
| Contact name | `[Authorized contact's full name]` |
| API interest | Select the choice covering Elation APIv2 / REST; confirm the displayed choice when submitting |
| Company | `[Legal entity developing CosmaBot]` |
| Email | `[Monitored business email]` |
| Phone | `[Business contact number]` |
| Agreement acceptance | Authorized representative reviews the agreement linked by the form before accepting |

Keep the application description below ready for Elation's follow-up; it is
not an observed free-text field on the form. Also identify a technical contact
and authorized signer if different from the form contact. Do not represent
CosmaBot as an existing Elation customer or approved partner.

The form links this [API agreement PDF](https://el8-tos-sandbox.s3.us-west-2.amazonaws.com/api-terms-of-service.pdf).
It includes eligible-customer and customer-BAA representations. Ask Elation how
those provisions apply to a prospective partner using only synthetic data.
The [public agreement page](https://www.elationhealth.com/api-license-usage-agreement/)
is dated December 2018; retain the version actually presented for acceptance.
No agreement has been accepted in this workstream.

Elation also has a separate [Become a Partner application](https://partners.elationhealth.com/application_forms/become-a-partner/partner_applications/new).
For that route, prepare the company website/address, partner category, product
description, employee/customer counts, existing EHR integrations, mutual Elation
customers, data needed and proposed service pricing. These business facts remain
owner-supplied. Report no qualified Elation integration yet; do not invent mutual
customers. Public documentation does not establish this extra application as a
prerequisite for the sandbox request.

## What to obtain

1. **A private sandbox practice and an administrator login.** Elation's
   [onboarding guide](https://help.elationhealth.com/articles/rest/overview/getting-started)
   describes provisioning an isolated, PHI-free practice. It initially has only
   the provisioning account; request guidance for adding test providers. Record
   the granted practice ID, display name, timezone and provider IDs in private
   installation configuration, not this document.
2. **A dedicated APIv2 key.** A sandbox practice admin can use **Settings →
   API Access → Create API Key**. Suggested name: `CosmaBot sandbox read test`.
   Choose **Elation APIv2** and save the secret directly into the approved
   encrypted credential store; it is displayed only once. The
   [credential guide](https://help.elationhealth.com/articles/self-service-api-credential-management)
   explains scope editing and revocation. Assign only the three scopes below;
   the broad “Set All to Read-Only” option grants more than this slice needs.
3. **Confirmation of the grant.** Confirm the key is restricted to the intended
   synthetic practice, supports these exact scopes, and is appropriate for a
   third-party partner test. Obtain the support contact, sandbox expiry/reset
   policy and any account-specific limits. These details remain unverified.

| Requested scope | CosmaBot use |
| --- | --- |
| `system/practices.read` | Verify the selected practice, timezone and provider references |
| `system/appointments.read` | Read a chosen time window and recheck the selected appointment |
| `system/patients.read` | Verify that appointment's patient identity |

The [scope catalog](https://help.elationhealth.com/articles/rest/overview/scopes)
documents these permissions. Use the documented
[client-credentials exchange](https://help.elationhealth.com/articles/rest/overview/get-token)
at `https://sandbox.elationemr.com/api/2.0/oauth2/token/`, with the three scopes
explicitly requested. CosmaBot requires the returned scope set to match exactly.
Omitting scope can default to broad `apiv2` access. This flow does not require a
clinician password, impersonation, redirect URI or callback server. Do not add
write scopes or `act_as_user` to the integration key.

## Synthetic test practice requirements

These are **CosmaBot qualification fixtures**, not signup requirements. Elation's
[access guide](https://help.elationhealth.com/core-developer-access) describes a
blank sandbox in which we create the test records. Arrange that with its
administrator; keep setup authority separate from the read key. The guide says
Technical Solutions emails access after submission, so no provisioning time is
promised here.

| Fixture | What it proves |
| --- | --- |
| One practice with a known IANA timezone and an active physician ID; a second test provider is useful | Correct practice and provider mapping |
| Invented patients with names, DOBs and primary physicians in that practice; include two similar identities | Staff can distinguish the intended appointment and patient |
| A nondeleted, selectable appointment with patient, physician, timezone-aware start and duration; an empty window, cancelled/deleted cases and a changed patient assignment | Correct selection and useful recovery without silent substitution |
| More than 25 appointments in a window and appointments at date/DST boundaries | Partial-page wording and device/practice timezone handling |
| A disposable second key; optionally a second separately owned test practice | Credential rotation/revocation and cross-practice denial |

Use only records belonging to our provisioned test accounts. If a second
practice or an error fixture is unavailable, retain the local regression and
mark that vendor check unverified. Do not guess another customer's identifiers
or generate traffic to force rate limiting. Ask for the vendor's supported
method to exercise throttling. The linked agreement specifies **fewer than
3 calls/second and fewer than 150,000 calls/24 hours**; confirm any stricter
sandbox limits.

## CosmaBot work before the first sandbox read

Possessing a key will not activate the current application. These are internal
engineering requirements; staff should eventually see the practice name and
one clear setup/recovery action, without entering credentials into chat.

- Add a separately gated, sandbox-only installation/runtime path. Preserve
  `SyntheticElationReads` as mock-only; production stays rejected. Current
  `WORKSPACE_EHR_READ_ENABLED` and `VITE_EHR_READ_ENABLED` defaults stay off.
- Extend the existing hash-checked `SecretReference` mechanism in
  `src/cosmas_os/adapters/managed_service_configuration.py` for private backend
  credential resolution. There is no working Elation credential installer yet.
  A raw key must never enter renderer storage, Git, chat, test receipts or logs.
- Bind Box, human owner, connection, credential generation and selected practice
  to the immutable `EhrReadBinding`. Recheck current authority before and after
  I/O and during recovery. A key change requires a new generation.
- Supply a shared credential request budget through `permit_request`; the
  adapter's per-instance limiter is insufficient across workers or machines.
  Preserve fixed-host requests, time/size bounds and no automatic retries.
- Run bounded qualification against invented records, then repeat the actual
  appointment → patient review → existing visit → Chief draft journey. Keep
  lost-reply recovery on the original command, preserve unsent text, and verify
  revocation withholds saved source content. Preparing a draft makes no model
  call and performs no chart write.

Implementation references: [adapter and application contract](../elation-read-integration.md),
`src/cosmas_os/adapters/elation_read_runtime.py`,
`src/cosmas_os/application/ehr_reads.py` and
[workstream checkpoint](EHR_CONNECTOR_WORKSTREAM_20261025.md).

## Acceptance and later production work

- [ ] Authorized sandbox access and applicable terms are documented privately.
- [ ] Test practice/admin, dedicated key, exact scopes and private installation are verified.
- [ ] Actual token/resource responses pass practice, identity, timezone and pagination checks; the qualification record names tested endpoints and includes `401`, `429` and `5xx` recovery evidence, distinguishing real responses from injected failures.
- [ ] The real sandbox-to-Chief draft journey passes with preserved drafts and recoverable lost replies.
- [ ] A rebuilt native client passes the same task on a physical device.

Production is a later gate: Elation's onboarding lists integration review,
written practice consent and separate production credentials, with pricing
available on request. Obtain partner licensing/practice charges and applicable
customer agreements before activation. CosmaBot also needs a reviewed production
host/identity configuration and **EHR retention/erasure implementation** before
storing real patient data. Its current immutable source history and artifact
purge do not erase EHR snapshots; revocation only withholds them. This packet
requests no prescriptions, clinical signing, booking, messaging or other writes.

## Draft request — not sent

**Subject:** CosmaBot — synthetic sandbox access for an Elation REST integration

Hello Elation Partnerships team,

We are developing CosmaBot, a practice assistant for independent clinics,
including DPC, concierge and RRM/NFP practices. We would like to evaluate an
integration as a prospective partner using a private, entirely synthetic
Elation APIv2 sandbox practice.

Our first workflow lets staff choose an existing appointment, check its patient
identity, review the source, and prepare an editable draft for CosmaBot's Chief
assistant. A local mocked prototype passes; we have not qualified it against
Elation. This phase has no real patient data, automatic AI invocation, chart
writes, prescribing, booking or patient messages.

Please confirm the sandbox onboarding path and whether administrator-created
APIv2 credentials are appropriate for this partner evaluation. We request only
`system/practices.read`, `system/appointments.read` and `system/patients.read`
using client credentials, restricted to our test practice.

Could you also confirm:

- Which agreement applies to a prospective partner's synthetic sandbox, given
  the eligible-customer and BAA language in the form's linked terms?
- How to seed invented patients/appointments and add test provider references,
  and whether a second test practice is available for isolation checks?
- Sandbox expiry/reset rules, supported revocation/throttling tests, and any
  limits beyond the published API limits?
- The partner approval process and fees for this vendor-built integration,
  including confirmation that participating practices use the partner-access
  path described in your FAQ?

Please provide credentials only through your supported secure provisioning
process. We do not need secrets in an email reply.

- Application: CosmaBot
- Legal entity: `[To be supplied]`
- Business contact: `[Name, role, business email, phone]`
- Technical contact / authorized signer: `[If different]`

Thank you.

---

Official sources above were checked October 25, 2026. Form submission, account
provisioning, agreement acceptance and vendor tests remain outstanding. No
images, live API calls or account changes were used to prepare this packet.
