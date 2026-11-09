# C9 — Today's schedule from athena FHIR Encounter

Tonight for existing live users: nothing changes. Both C8 flags stay off. Hosted
and production refuse the sandbox flag. No live athena calls run in CI. The C14
real-data lock stays on. Booked appointments (C15) stay parked.

## What this replaces

The schedule path that called Core `/embed/v1/athena/appointments/read` (that
route does not exist). CosmaBot now builds today's schedule from Certified FHIR
R4 **Encounter** reads against athena Preview practice **195900**.

| Surface | Behavior |
| --- | --- |
| `POST /connections/cosmaneura/read` | `athena_connection` / `athena_appointments` when C8 flags are on |
| Existing schedule UI | Same `AthenaScheduleResponse` contract; data source only |
| CosmaBot plugin | `athena_read_appointments` unchanged; backend source swaps |
| Adapter | C7 `AthenaFhirR4Adapter` Encounter search |
| Mapping | C5 `map_encounter_to_schedule` |
| Auth | C2 client-secret via existing secret refs |
| Transport in CI | `httpx.MockTransport` + fake env vault only |

## Flags (both required, both default off)

- `WORKSPACE_EHR_READ_ENABLED`
- `WORKSPACE_ATHENA_FHIR_SANDBOX_ENABLED`

When both are available, the schedule path uses Encounter FHIR and never calls
Core appointments/read. When either is off, today's schedule behaves exactly as
before (empty / unchanged for existing users; no new error walls).

## Guards that must hold

- athena Preview only, with `ah-practice=Organization/a-1.Practice-195900`
- Exactly the existing 12 scopes; no Appointment scope and no FHIR Appointment calls
- Shared C4 host and resource allowlists are not widened
- Every closed-flag / C14 refusal happens before token mint or FHIR HTTP
- Audit / logs stay PHI-free; canary secrets and tokens never appear in logs,
  errors, or responses
- Hosted configs that set the athena FHIR sandbox flag still fail startup
  validation (C8)

## Not in this ticket

- Live Preview smoke or Key Vault creation (J2)
- Non-Certified booked appointments (C15)
- Flag flips in hosted or production
- Schedule UI redesign, infra, or deploy files
