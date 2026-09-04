# Capability matrix (local synth / deployed D2 / prepared D3)

| Capability | State | Notes |
|---|---|---|
| Box / principals / F-8 | ON | Local workflow proven; same application image is deployed to D2, but the full cloud workflow was not re-run |
| SchedulePort L0 CSV | ON | Invented appointments only |
| NotifyPort L0 fake | ON | In-memory sink; no real delivery |
| PostgreSQL | ON | Local Compose plus D2 Azure synth database; Azure public networking and `AllowAzureServices` are D2-only |
| Celery / Redis transport | ON | D2 uses `SYNC_WORKER=false`; worker is broker-connected and ready |
| BlobPort local FS | ON | Local `data/blobs`; D2 `/tmp/cosmas-os-blobs` is ephemeral and per replica |
| Azure Blob adapter | IMPLEMENTED / D3 CLOUD VALIDATION BLOCKED | Managed-identity adapter and Box-prefixed keys have offline tests; D2 does not consume it and no D3 workload/artifact storage exists |
| D3 database preparation | IMPLEMENTED / LIVE EVIDENCE BLOCKED | Manual unscheduled digest-pinned in-network job creates/verifies the non-admin role, applies the sole Alembic head, proves DDL and audit-mutation denial, and emits sanitized evidence |
| AuthPort synth headers | ON IN SYNTH ONLY | Active-human and Box lookup enforced; beta rejects these caller-provided headers |
| AuthPort Clerk JWT | IMPLEMENTED / LIVE LOGIN DARK | Exact issuer, audience, authorized party, Org, signature, and reviewed database binding are enforced offline; the development Clerk application and empty development Beta Lab Organization are configured, while production configuration and human login evidence are missing |
| PatientLink attestation | ON | Blocks chase when unconfirmed |
| Insurance ArtifactChase | ON | Local proof ends at `IMAGE_ON_FILE` |
| Retention purge | ON | Closed + 7d via injectable clock |
| Azure D2 synth runtime | ON | Digest-pinned API/worker, Key Vault/UAMI connection refs, migration head, health and worker readiness verified |
| Azure D3 isolated runtime | BOOTSTRAP DEPLOYED / APPLICATION NOT DEPLOYED | The isolated state boundary, dedicated Box assignment, two D3 resource groups, and protected runner exist; capacity, application foundation, database job, and workload applies remain pending |
| D3 web login/hosting | SOURCE IMPLEMENTED / LIVE DARK | Local synthetic UI is testable, the development Clerk structure exists, and `beta.cosmaneura.com` is the accepted production origin; the production key/Organization, foundation-derived API host, web revision, DNS, and custom-domain binding remain absent |
| Athena / Acuity | DARK | Fail closed |
| Real email / SMS / A2P | DARK | Fail closed |
| Teams | DARK | Fail closed |
| Patient payment / PAN | DARK | Forbidden in v1 |
| Evidence / Workbook | DARK | Deferred |
| Application LLM | DARK | Not a runtime dependency |
| `AUTO_TEMPLATE` send | DARK | Rejected |
| `AUTO_DRAFT` send | DARK | Staff surface only |

D2 remains public, synthetic-only infrastructure—not an isolated early-adopter
beta. D3's isolated bootstrap and protected runner exist, but application
deployment remains blocked on Azure capacity, a committed CI-green successor
release, the foundation, production Clerk Organization/readback, live database
preparation, exact-plan cost/network evidence, workload/domain progression, and
human acceptance. A named clinic, clinic approval, BAA review, and separate PHI
authorization apply only to a later `authorized_beta` deployment. PHI is not
authorized.
