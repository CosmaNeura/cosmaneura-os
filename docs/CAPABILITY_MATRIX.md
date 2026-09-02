# Capability matrix (L0 synth)

| Capability | State | Notes |
|---|---|---|
| Box / principals / F-8 | ON | Local Postgres |
| SchedulePort L0 CSV | ON | Fake appointments |
| NotifyPort L0 fake | ON | In-memory sink |
| BlobPort local FS | ON | `data/blobs` |
| AuthPort fake | ON | Header principal ids |
| PatientLink attestation | ON | Blocks chase when unconfirmed |
| Insurance ArtifactChase | ON | Ends at IMAGE_ON_FILE |
| Retention purge | ON | closed + 7d via clock |
| Athena / Acuity | DARK | Fail closed |
| Real email / SMS / A2P | DARK | Fail closed |
| Teams | DARK | Fail closed |
| Patient payment / PAN | DARK | Forbidden in v1 |
| Evidence / Workbook | DARK | Deferred |
| Clerk / Azure | DARK | Not wired in synth |
| Application LLM | DARK | Not a runtime dependency |
| AUTO_TEMPLATE send | DARK | Rejected |
| AUTO_DRAFT send | DARK | Staff surface only |
