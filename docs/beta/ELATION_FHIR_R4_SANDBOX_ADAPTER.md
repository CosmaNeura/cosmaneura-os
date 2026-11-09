# Elation FHIR R4 sandbox adapter (C11 / C20 / T4)

Tonight for existing live users: nothing changes. This adapter is not wired into
CosmaBot routes beyond the existing Elation REST path. Flags stay off. No live
Elation calls run in CI. No sandbox signup and no new secrets are provisioned
by this ticket.

## Hybrid choice: FHIR + REST

| Need | Path | Why |
| --- | --- | --- |
| Patient, Encounter, Condition, MedicationRequest, AllergyIntolerance, Observation, DocumentReference, DiagnosticReport, Binary, Medication, Practitioner, Organization | **FHIR R4** (`adapters.elation_fhir_r4`) | Elation's ONC (g)(10) FHIR API documents exact `system/<Resource>.read` scopes for these. Shared C4 client + C2 client-credentials. |
| Appointments / practice verification | **REST APIv2** (`adapters.elation_read`, sandbox runtime, plugin tools) | Elation's published `system/*.read` expansion does **not** include Appointment. Existing client-credentials REST already covers schedule reads. Do not duplicate. |

Separate Elation API keys are required for APIv2 vs FHIR (credential type is
fixed at creation). FHIR vault reference **names** are documented below; John
creates values after the sandbox / API agreement packet. REST credentials stay
on the existing Elation path.

## What this is

| Setting | Value |
| --- | --- |
| FHIR base URL | `https://sandbox.fhir.elationemr.com/fhir` |
| Token URL | `https://sandbox.fhir.elationemr.com/smart/token` |
| Auth | C2 client-secret token provider |
| Secret refs | `COSMAS_MANAGED_SECRET_EHR_ELATION_FHIR_CLIENT_ID` / `_CLIENT_SECRET` |
| Transport in CI | `httpx.MockTransport` only |

## Approved FHIR scopes (exact, no wildcards, no write, no Appointment)

`system/Patient.read`, `system/Encounter.read`, `system/AllergyIntolerance.read`,
`system/MedicationRequest.read`, `system/Medication.read`, `system/Condition.read`,
`system/Observation.read`, `system/DiagnosticReport.read`,
`system/DocumentReference.read`, `system/Binary.read`,
`system/Practitioner.read`, `system/Organization.read`.

FHIR **Appointment** is refused with `use_rest_appointments`. Schedule stays on
REST.

## Guards

- C14 real-data / hosted / production origin gate (`assert_ehr_request_allowed`)
  for both REST (`sandbox.elationemr.com`) and FHIR (`sandbox.fhir.elationemr.com`)
- Sandbox flag required; real-data / production origins refused by default
- Narrowed token grants refuse resources whose `system/<Resource>.read` scope
  was not granted
- Tokens and client secrets never appear in logs or exception text
- Shared C4 defaults are not widened: Elation FHIR host is passed only via
  `extra_sandbox_hosts=`, and DiagnosticReport/Binary only via
  `allowed_resources=` on the Elation adapter's FHIR client
- PHI-free search/read log lines (resource type, count, outcome only)

## Not in this ticket

- Route wiring into `/connections/ehr/reads` beyond the existing Elation REST tools
- Live sandbox signup, vendor contact, or Key Vault secret creation
- Web/UI, infra, or deploy changes
- Production origins or real practice data
