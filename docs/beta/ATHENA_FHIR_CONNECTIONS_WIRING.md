# C8 — Wire athena FHIR into Connections and CosmaBot tools

Tonight for existing live users: nothing changes. Both flags stay off. Hosted
and production refuse the sandbox flag. No live athena calls run in CI. The C14
real-data lock stays on.

## What this wires

| Surface | Behavior |
| --- | --- |
| `POST /connections/ehr/reads` | `provider=athena` + `protocol=fhir` for `status`, `fhir_patients`, `fhir_medications` |
| CosmaBot plugin tools | `athena_read_authorized_patients`, `athena_read_fhir_medications` |
| Adapter | C7 `AthenaFhirR4Adapter` (Preview practice 195900) |
| Mapping / custody | C5 US Core → shared FHIR grant and source-review path |
| Auth | C2 client-secret via `COSMAS_MANAGED_SECRET_EHR_ATHENA_FHIR_CLIENT_ID` / `_CLIENT_SECRET` |
| Transport in CI | `httpx.MockTransport` + fake env vault only |

## Flags (both required, both default off)

- `WORKSPACE_EHR_READ_ENABLED`
- `WORKSPACE_ATHENA_FHIR_SANDBOX_ENABLED`

`workspace_athena_fhir_sandbox_available` is true only when EHR reads are
available and the athena FHIR sandbox flag is on. Hosted configs that set the
athena FHIR sandbox flag fail startup validation. Production origins stay
refused by C14 unless the real-data switch and practice BAA are both set
(neither is flipped here).

## Guards that must hold

- Every refusal for a closed flag or C14 gate happens before token mint or FHIR HTTP
- Exactly the 12 approved `system/<Resource>.read` scopes; no Appointment scope or calls
- Shared C4 default host and resource allowlists are not widened
- Audit / provenance stay PHI-free; canary secrets and tokens never appear in logs, errors, or responses
- Credentials resolve only by `COSMAS_MANAGED_SECRET_*` reference names

## Not in this ticket

- Live Preview smoke or Key Vault creation (J2)
- Appointment UI path (C9) or Non-Certified appointments (C15)
- Flag flips in hosted or production
- Web UI redesign, infra, or deploy files
