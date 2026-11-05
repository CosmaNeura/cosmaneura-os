# Shared FHIR R4 / US Core read client

This package is a vendor-neutral FHIR R4 read helper for CosmaBot EHR work. It
lives at `src/cosmas_os/plugins/ehr_fhir/` and does not register CosmaBot tools,
change the tool registry, or alter Athena / Elation / Tebra / Atlas.md plugin
behavior. A separate ticket owns `plugins/ehr` and the `EhrConnector`
interface; this client stays self-contained so those PRs do not conflict, and
it can plug into that interface later.

Merging this change does not deploy it. People using CosmaBot today do not see
any new tools or behavior from this package.

## What it reads

Only these FHIR R4 / US Core resource types, by instance read or search:

| Resource | Typical use |
| --- | --- |
| `Patient` | Identity for an already authorized chart |
| `Encounter` | Visit context |
| `Appointment` | Scheduled visit rows |
| `AllergyIntolerance` | Allergy list |
| `MedicationRequest` | Medication orders and plans |
| `Medication` | Medication catalog records referenced by orders |
| `Condition` | Problem list |
| `Observation` | Vitals and results |
| `DiagnosticReport` | Lab and imaging report metadata |
| `DocumentReference` | Clinical document metadata |
| `Binary` | Document / report content bytes |
| `Practitioner` | Clinician identity |
| `Organization` | Practice or clinic organization |

Search returns Bundle `searchset` pages. The client follows `link.relation=next`
only while the next URL stays on the same accepted base origin and path prefix.
Hard defaults:

- at most 5 pages
- at most 262,144 response bytes across followed pages
- GET only; redirects are not followed

Empty pages are still a successful read. The message says an empty page does
not mean the chart is empty.

## Plain error states

Failures map to the same state names and message wording the existing connector
plugins already show, plus two ehr_fhir-lane additions. Pass a display label
such as `Athena`, `Elation`, `Tebra`, or `EHR`:

| State | When it happens |
| --- | --- |
| `ready` | One or more pages were read within the limits |
| `not_connected` | HTTP 404, connect failure, or OperationOutcome `not-found` / `not-supported` |
| `expired` | HTTP 401/403, or OperationOutcome `login` / `expired` / `security` / `forbidden` |
| `wrong_practice` | HTTP 421, or OperationOutcome `multiple-matches` |
| `malformed` | Bad JSON, wrong resource type, size limit, or structure errors |
| `timeout` | HTTP 408/504, read timeout, or OperationOutcome `timeout` / `transient` |
| `stale` | HTTP 409/412, off-origin next link, or OperationOutcome `deleted` / `superseded` |
| `rate_limited` | HTTP 429 |
| `refused` | Write verbs refused before transport |

When an error response carries both an HTTP status and an OperationOutcome
issue code, the HTTP status mapping wins. Chart rows are returned only for
`ready`.

## Read-only and sandbox-only defaults

- Write verbs (`POST`, `PUT`, `PATCH`, `DELETE`, and the client `create` /
  `update` / `patch` / `delete` / `post` / `put` helpers) are refused before
  any transport call and return `refused`.
- Base URLs must use an exact allowlisted sandbox host name
  (case-insensitive equality on the parsed hostname only). The allowlist is
  `fhir.sandbox.example.com`, `sandbox.fhir.example.org`, `synthetic.invalid`,
  `mock.example.com`, `localhost`, `127.0.0.1`, and athena Preview
  `api.preview.platform.athenahealth.com`. Look-alike hosts such as
  `test.evil.com`, `mock-athena.example.net`, or `sandbox.attacker.io` are
  refused. Trailing-dot host names, plain HTTP to non-local hosts, and URLs
  with userinfo are refused. Athena production hosts stay refused by default.
- Production hosts (`prd`, `prod`, `production`, `live`) raise
  `PermissionError` unless `allow_production=True` is set explicitly. That
  opt-in is not wired to live credentials here. The real-data switch stays off.

## Tests and fixtures

Unit tests under `tests/unit/test_ehr_fhir_*.py` use
`tests/unit/fixtures/ehr_fhir/*.json`: recorded, invented US Core-shaped
resources (Avery Northwind and related synth IDs only). Transport is
`httpx.MockTransport`. Tests do not open the network.

## Out of scope

- No CosmaBot tool registration or receipt changes
- No `plugins/ehr` package and no `EhrConnector` edits
- No OAuth, token storage, vendor sign-up, deploy, or live FHIR calls
- No write / create / update / delete clinical actions
