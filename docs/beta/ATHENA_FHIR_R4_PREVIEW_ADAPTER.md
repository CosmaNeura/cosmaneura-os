# athena Certified FHIR R4 Preview adapter (C7)

Tonight for existing live users: nothing changes. This adapter is not wired into
CosmaBot routes, plugin tools, or production config. Flags stay off. No live
athena calls run in CI.

## What this is

Sandbox-only adapter for athena's Certified FHIR R4 API against the public
Preview practice **195900**.

| Setting | Value |
| --- | --- |
| Base URL | `https://api.preview.platform.athenahealth.com/fhir/r4` |
| Practice scope | every search carries `ah-practice=Organization/a-1.Practice-195900` |
| Auth | C2 client-secret token provider (`oauth2/v1/token`) |
| Secret refs | `COSMAS_MANAGED_SECRET_EHR_ATHENA_FHIR_CLIENT_ID` / `_CLIENT_SECRET` |
| Transport in CI | `httpx.MockTransport` only |

## Approved scopes (exact, no wildcards, no write, no Appointment)

`system/Patient.read`, `system/Encounter.read`, `system/AllergyIntolerance.read`,
`system/MedicationRequest.read`, `system/Medication.read`, `system/Condition.read`,
`system/Observation.read`, `system/DiagnosticReport.read`,
`system/DocumentReference.read`, `system/Binary.read`,
`system/Practitioner.read`, `system/Organization.read`.

FHIR **Appointment** is refused. Encounter is the schedule source for now. The
Non-Certified appointments path stays parked (C15). C9 will use Encounter only
for the appointments UI path.

## Guards

- C14 real-data / hosted / production origin gate (`assert_ehr_request_allowed`)
- Practice override or off-origin search/paging refused
- Narrowed token grants refuse resources whose `system/<Resource>.read` scope
  was not granted
- Tokens and client secrets never appear in logs or exception text
- Shared C4 defaults are not widened: athena Preview host is passed only via
  `extra_sandbox_hosts=`, and DiagnosticReport/Binary only via
  `allowed_resources=` on the athena adapter's FHIR client

## Follow-on

- Route wiring into `/connections/ehr/reads` and plugin tools is C8
  (`docs/beta/ATHENA_FHIR_CONNECTIONS_WIRING.md`). Flags stay off.
- Appointment UI path (C9)
- Live Preview smoke (Nov 5 override: mock/recorded CI only; do not wait on J2)
- Key Vault creation (John / J2) — tests use a fake env vault only
