# Tebra SOAP read adapter

`adapters/tebra_read.py` implements three bounded SOAP operations: an exact
practice check, a patient search by surname and birth date, and a patient
appointment read over at most seven elapsed days. These return immutable,
minimal observations. They do not create a connected-account UI or a runtime
readiness claim.

The adapter is **inactive by default and limited to explicitly supplied
`httpx.MockTransport` instances**. Enabling it without a synthetic transport
returns `provider_qualification_required` before creating an HTTP client. No
production transport, vendor account, app route, secret store, background poll,
write operation, or new dependency is installed by this slice.

## Contract evidence

The implementation was checked against the vendor's public [SOAP 2.1
WSDL](https://webservice.kareo.com/services/soap/2.1/KareoServices.svc?singleWsdl)
on October 25, 2026. That document was 601,360 bytes with SHA-256
`1a241e25884069db91726e09ba37af56d05e53659fb65fa5b6e4f91c5cd5fdc7`.
Only public schema metadata was retrieved; no authenticated API method was
called, and the WSDL is not downloaded at runtime.

The [April 2026 API Integration Technical
Guide](https://kareocustomertraining.s3.amazonaws.com/Help%20Center/Guides/Tebra%20API%20Integration%20Technical%20Guide.pdf)
and [SOAP setup
instructions](https://helpme.tebra.com/Tebra_PM/12_API_and_Integration) supply the
operation descriptions and access prerequisites. The WSDL distinguishes the
bulk appointment fields `StartDate`/`EndDate` from single-appointment fields.
It also places `RequestHeader` inside the operation's request body, before
`Fields` and `Filter`.

## Access and data handling

- `TebraReadScope` binds the expected vendor account/practice to a CosmaBot Box,
  owner, connection, and credential generation.
- The mandatory `authorize_read(scope)` callback belongs to the application.
  It must authenticate the actual CosmaBot caller, authorize that caller for
  the Box, and compare the current connection generation. It runs before and
  after the read. A successful Tebra credential response cannot authorize a
  CosmaBot principal or substitute for that callback.
- `TebraCredentials` is supplied per call using `SecretStr`. No secret is saved
  on the adapter or attached to its result. The eventual server integration
  must resolve opaque secret references; this is not a frontend credential
  flow. Never enable raw HTTP/SOAP body logging or exception-local capture.
- SOAP uses an exact fixed origin, no redirects, no ambient proxy credentials,
  and a fresh short-lived HTTP client. Vendor faults and exceptions map to
  fixed local error codes. No retries occur here.
- The response budget is 256 KiB, 100 rows, 4,096 XML elements, and depth 16.
  DTD and entity declarations are rejected by parser callbacks before
  expansion, including UTF-16 input. Compressed responses are rejected. An
  oversized result fails and requires a narrower query; it is not silently
  truncated into success.
- Account ID and authorized practice IDs must match the expected scope.
  Returned practice labels match exactly. Appointment rows also carry and
  validate a numeric practice ID. Patient rows do not expose that field in
  this WSDL, so the request includes both the exact numeric practice filter
  and practice name; authorization evidence and returned labels are checked.
- Responses return only selected fields, reject duplicate IDs and invalid
  intervals, and preserve explicit timestamp offsets as UTC instants.
  `coverage=returned_rows_only` deliberately makes no complete-list or
  availability assertion. An empty schedule response is not proof of a free
  slot. Multiple patient candidates remain candidates, never an automatic
  patient match.

## Required provider qualification before live activation

The current synthetic success fixture requires explicit true values for
`Authenticated`, `Authorized`, `CustomerKeyValid`, and `SecurityResultSuccess`,
the exact text `SecurityResult=Success`, an explicit non-error envelope, empty
missing permissions, and the authorized practice ID. **That status spelling
and boolean meaning are fixture assumptions, not certified vendor behavior.**
The guide contradicts itself about the meaning of `SecurityResultSuccess`.
There is no configurable boolean polarity or user-adjustable success mapping.
Resolve this with corrected vendor documentation or approved synthetic
vendor evidence before replacing the transport restriction.

Also qualify:

1. Actual success/failure envelope optionality and nil values, permission-array
   shape, and account identity behavior. Missing or conflicting evidence
   currently fails closed.
2. Exact practice-filter behavior for patient reads, particularly accounts
   whose practices share the same display name.
3. Date formatting and timezone semantics for bulk appointment reads when
   requesting GMT offset zero. Naive response timestamps are rejected rather
   than silently assigned a timezone. Verify date-window boundaries and DST.
4. Patient birth-date formatting, patient appointment types, and confirmation
   status vocabulary. Unsupported values currently fail closed.
5. Bulk result completeness/limits. This WSDL exposes no list total or cursor;
   the implementation does not invent pagination or availability guarantees.
6. A supported isolated SOAP sandbox, administrator/API access, and permitted
   commercial integration use. FHIR My Sandbox is a different interface and
   does not establish SOAP sandbox access.

Future installation should use the existing managed-service/secret machinery
and selected-source path. Keep authentication separate from any read source
chosen for Chief. Do not extend the delivery-vendor enum just to install an
EHR read service. Account-level pacing belongs in existing runtime controls;
this adapter creates no scheduler or retry queue.

Clinical FHIR reads, document uploads, scheduling writes and eRx require
separate capability work. The adapter offers no generic operation entry
point, and its internal dispatch still rejects all operation names outside
the three read methods. Future writes must use the existing F-8 authority,
immutable approval binding, and exact-outcome reconciliation.

## Synthetic verification

Run `python -m pytest -q tests/unit/test_tebra_read.py` and
`ruff check src/cosmas_os/adapters/tebra_read.py tests/unit/test_tebra_read.py`
in the isolated integration checkout. Tests use invented identifiers and
streaming mock responses; they perform no vendor calls. Coverage includes
SOAP shape/escaping, disabled and unqualified access, caller/Box scope,
credential-generation changes during I/O, security contradictions,
cross-practice data, malformed/hostile XML, response budgets, time windows,
HTTP failures and unreachable writes.
