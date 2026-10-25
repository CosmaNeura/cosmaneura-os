# Elation sandbox access packet

Updated October 25, 2026 for **CosmaBot**. The default-off managed sandbox
installation and appointment-review workflow are implemented and tested with
invented responses. The access request is **not sent**, a vendor sandbox is
**not provisioned**, and no vendor qualification is claimed.

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
   the granted practice ID, display name and timezone in private installation
   configuration. Keep test provider IDs in the private qualification record,
   not this document.
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

## Operator setup before the first sandbox read

The software path is implemented. A key alone does not activate it, and the
current tests have not used a vendor account. After approved access is obtained:

1. **Prepare the private installation.** Bring the local database through the
   additive `n13f9b2d7654` migration in the normal reviewed setup process. Use
   the existing managed-service configuration (`version: 1`, exact `box_id`) with one
   `elation_sandbox` entry for the intended human account. Its fields are
   `id`, `owner_id`, `account_id`, `connection_id`, `credential_generation`,
   `practice_id`, `practice_name`, `timezone`, `environment: "sandbox"`,
   `data_classification: "synthetic_only"`, `client_id` and `client_secret`.
   IDs and practice metadata come from the authorized local identity and vendor
   setup; staff does not enter them in the renderer. A new credential version
   requires a new generation and an explicit installation review.
2. **Supply exact secret references.** `client_id` and `client_secret` each use
   the existing `SecretReference` shape `{environment, sha256}`. The environment
   name must begin `COSMAS_MANAGED_SECRET_`; the digest pins the exact value.
   The operator supplies those private process values from approved credential
   custody. Raw keys never belong in the configuration document, repository,
   chat, renderer storage, receipts or diagnostics. Load either
   `MANAGED_SERVICES_CONFIG_PATH` or `MANAGED_SERVICES_CONFIG_JSON`, with the
   matching `MANAGED_SERVICES_CONFIG_SHA256`. Configuration loading performs no
   provider calls or account activation.
3. **Enable only the approved local test installation.**
   `WORKSPACE_EHR_READ_ENABLED`, `WORKSPACE_ELATION_SANDBOX_ENABLED` and
   `VITE_EHR_READ_ENABLED` all default off. The backend also requires an
   authenticated Clerk workspace with an external identity and rejects hosted
   mode for this slice. The managed runtime uses the fixed Elation sandbox
   origin; production, arbitrary host URLs and non-synthetic classification are
   rejected. The separate local-example runtime remains mock-only; both runtimes
   cannot be installed together.
4. **Let the intended person review setup.** From Chief's **Details → Notes and
   sources**, or the visit's **Sources**, choose **Review Elation appointment**.
   **Check Elation access** shows the configured practice. **Use this practice’s
   Elation sandbox** records that person's exact local installation; it does not
   contact Elation. An interrupted step offers **Check saved setup result**.
   Recovery checks the original command, and only a confirmed missing result
   permits the person to explicitly resend that same command. A saved setup
   receipt does not prove vendor access; the screen checks current setup again.
5. **Qualify the read and review journey.** Explicitly load a date window,
   choose an appointment, check its patient and intended visit, then save the
   reviewed source. **Prepare Chief draft** preserves unsent directions and
   makes no model call or chart write. The display distinguishes **Local
   example** from **Elation sandbox — invented test data**. A failed or lost read
   offers recovery of the saved request before any new read.

The shared request quota counts token and resource calls by client-ID digest
across processes using the same database, including credential generations.
It stays below the published limits, releases quota locks before sleeping or
provider I/O, and bounds SQL contention. Database connection acquisition retains
the existing host factory's timeout behavior. Use a dedicated test client: this
budget cannot measure other applications or deployments using the same key
outside that database. Confirm stricter vendor limits before qualification.

Signed API/database checks validate exact installation recovery, secret
rotation, transport integrity, access withholding and quota contention. Shared
UI checks validate setup recovery and preserved drafts using invented service
responses. These are software checks, not vendor acceptance. Implementation
and evidence references are in the [adapter and application contract](../elation-read-integration.md)
and [workstream checkpoint](EHR_CONNECTOR_WORKSTREAM_20261025.md).

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
assistant. The managed sandbox installation and workflow pass local tests with
invented responses; we have not qualified them against Elation. This phase has
no real patient data, automatic AI invocation, chart writes, prescribing,
booking or patient messages.

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

## Optional problem-list read

The appointment-only key still requests exactly the three scopes above. Reading
chart problems needs a separate, explicitly approved addition:
[`system/problems.read`](https://help.elationhealth.com/articles/rest/overview/scopes.md).
Do not infer it from `system/patients.read`, omit scopes, or request broad `apiv2`.
For this optional profile the token request and returned grant must contain
exactly those three scopes plus `system/problems.read`; no write or prescribing
permission is added.

After Elation authorizes that profile, use a new credential generation and new
installation review. Set the private installation's `problems_enabled: true`
and the host's `WORKSPACE_ELATION_PROBLEMS_ENABLED=true`; both default off.
The installation commitment includes the optional clinical scope. Changing the
profile invalidates the previous installation commitment. The renderer never
collects keys or lets staff add scopes. Installation still performs no vendor
call and does not prove access. The required additive source migration is
`r57d3f6b1098` after the preceding migrations.

The staff action follows a verified appointment. The server rereads that exact
appointment and its bound patient, compares the retained identity, then makes
one `GET /api/2.0/problems/` with exact patient, practice and `limit=25` filters.
No caller supplies a patient ID or continuation URL. The selected summary shows
only description, status, start/resolved dates and the provider's verification
status. It explicitly excludes diagnosis codes and synopsis, records partial or
unknown page coverage, and never interprets an empty page as absence of disease.
A summary exceeding 5,000 characters is refused without truncation. The same
saved-command recovery and human source review apply; reading does not prescribe
or write to a chart.

Before claiming vendor qualification, exercise the approved sandbox with
invented Active/Controlled/Resolved rows; confirmed, provisional, differential,
unconfirmed, refuted and entered-in-error verification; missing/blank verification;
empty and more-than-25 result sets; exact patient/practice mismatch denial;
changed patient identity; grant withdrawal; and lost read replies. Confirm the
current problems endpoint's optional `count`/`next` metadata and positive offset
format with Elation. Missing metadata remains unknown; the implementation never
follows a continuation. These are pending vendor checks, not completed live tests.
The public reference is the current
[patient profile schema](https://help.elationhealth.com/openapi/patient-profile-api.yaml),
retrieved October 25, 2026; its document hash and the scope reference are retained
in this workstream's `evidence/elation-clinical-reference` packet.
