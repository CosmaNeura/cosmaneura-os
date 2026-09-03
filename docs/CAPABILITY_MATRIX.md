# Capability matrix (L0 synth / D2 Azure)

| Capability | State | Notes |
|---|---|---|
| Box / principals / F-8 | ON | Local workflow proven; same application image is deployed to D2, but the full cloud workflow was not re-run |
| SchedulePort L0 CSV | ON | Invented appointments only |
| NotifyPort L0 fake | ON | In-memory sink; no real delivery |
| PostgreSQL | ON | Local Compose plus D2 Azure synth database; Azure public networking and `AllowAzureServices` are D2-only |
| Celery / Redis transport | ON | D2 uses `SYNC_WORKER=false`; worker is broker-connected and ready |
| BlobPort local FS | ON | Local `data/blobs`; D2 `/tmp/cosmas-os-blobs` is ephemeral and per replica |
| Azure Blob adapter | DARK | Storage/container provisioned, but the application does not consume it |
| AuthPort fake | ON | Caller-provided identity headers; this is not authentication and is unsafe for PHI |
| PatientLink attestation | ON | Blocks chase when unconfirmed |
| Insurance ArtifactChase | ON | Local proof ends at `IMAGE_ON_FILE` |
| Retention purge | ON | Closed + 7d via injectable clock |
| Azure D2 synth runtime | ON | Digest-pinned API/worker, Key Vault/UAMI connection refs, migration head, health and worker readiness verified |
| Clerk | DARK | No login or Clerk Org wiring |
| Athena / Acuity | DARK | Fail closed |
| Real email / SMS / A2P | DARK | Fail closed |
| Teams | DARK | Fail closed |
| Patient payment / PAN | DARK | Forbidden in v1 |
| Evidence / Workbook | DARK | Deferred |
| Application LLM | DARK | Not a runtime dependency |
| `AUTO_TEMPLATE` send | DARK | Rejected |
| `AUTO_DRAFT` send | DARK | Staff surface only |

D2 is public, synthetic-only infrastructure—not an isolated early-adopter beta.
D3 remains gated and must add real human authentication and stronger network,
storage, and tenant isolation before PHI is possible.
