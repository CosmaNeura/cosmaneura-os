# C5 — US Core → CosmaBot FHIR custody mapping

Tonight for existing live users: nothing changes. This work unlocks the shared
FHIR PatientLink grant and human source-review path for athena Preview and maps
synthetic US Core resources into review provenance. Route and plugin wiring is
C8 (`docs/beta/ATHENA_FHIR_CONNECTIONS_WIRING.md`). Flags stay off. No live calls.

## What already existed

- Shared C4 FHIR R4 / US Core read client and synthetic fixtures
- C7 athena Preview adapter (practice 195900) — not route-wired
- Tebra-only FHIR custody: `EhrFhirPatientGrant`, `fhir_patients` /
  `fhir_medications`, SQL digests/guards, and source-review admission

## Smallest unlock

Reuse the Tebra FHIR custody tables and review flow. Make digests, checks, and
ports vendor-aware so athena Preview is accepted without a second custody
system and without changing Tebra digest bytes.

| Vendor | protocol | environment | FHIR base |
| --- | --- | --- | --- |
| tebra | fhir | synthetic | `https://fhir.prd.cloud.tebra.com/fhir-request` |
| athena | fhir | preview | `https://api.preview.platform.athenahealth.com/fhir/r4` (+ `ah-practice=Organization/a-1.Practice-195900`) |

## Mapping surface

`application/ehr_fhir_us_core_mapping.py` maps synthetic US Core resources into:

- Patient → PatientLink / `EhrFhirPatientGrant` identity pin
- MedicationRequest, Encounter, AllergyIntolerance, Condition, Observation,
  DocumentReference → source-review projections with provenance
  (`vendor`, `resource_type`, `resource_id_hash`, `read_time`)

Appointment is not mapped for athena (C15 / Non-Certified parked). C9 maps
Encounter into the existing schedule row shape via `map_encounter_to_schedule`.
No proprietary athena Appointment calls and no FHIR Appointment reads.

## Follow-on

- Route wiring and plugin tools (C8)
- Today's schedule from Encounter (C9 — `docs/beta/ATHENA_FHIR_TODAY_SCHEDULE.md`)
- Live Preview calls, Key Vault, or flag flips
