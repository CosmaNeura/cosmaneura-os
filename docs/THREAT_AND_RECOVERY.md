# Threat and recovery model (L0)

## Threats in scope for synth

| Threat | Mitigation |
|---|---|
| Agent self-approval | Reject non-human Decision actors |
| Duplicate outreach | Unique operation per action revision; NotifyPort idempotent by operation_id |
| Edit after approve | Edit invalidates revision; new approval required |
| Dark connector misuse | CapabilityConfig empty by default; enforce fail-closed |
| PHI in fixtures/logs | Invented data only; fixture scan; audit detail without image bytes/paths of purged content |
| Last-owner lockout | Refuse remove without successor |

## Recovery

| Failure | Behavior |
|---|---|
| Crash before notify ack | Operation stays PENDING or UNKNOWN; retry reuses same operation_id |
| Unconfirmed external result | Status UNKNOWN; reconcile from receipt — no blind second send |
| Broker loss | Postgres remains authority; re-enqueue PENDING ops |
| Disabled Chaser | Cannot open new chase; history retained |

## Out of scope for this slice

Network attackers, real IdP compromise, cloud IAM (INV-6), live EHR reconciliation.
