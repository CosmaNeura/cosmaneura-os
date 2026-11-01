# Shared EHR connector contract

This document describes the small, stable interface in
`src/cosmas_os/plugins/ehr/`. It is the shared contract for athenaOne, Elation,
Tebra, and Atlas.md capability declarations. Later work hangs off this surface
without changing CosmaBot plugin tool behavior.

Tonight for existing live users: no change. Nothing deploys; this package is a
sandbox-only declaration layer.

## What this package is

| Piece | Module | Role |
| --- | --- | --- |
| Capability manifest | `manifest.py` | Declares readable resources, auth styles, sandbox/production claims, and explicitly unsupported actions |
| Connector interface | `connector.py` | `EhrConnector` protocol and `DeclaredEhrConnector` with fail-closed gates |
| Vendor registry | `registry.py` | In-process map of the four vendors |
| Hook points | `hooks.py` | Empty Protocols for C2–C4, C6, and C14 |
| Refusals | `refusals.py` | Closed error codes for write, target, and read refusals |

Each existing plugin module exports `EHR_CAPABILITY`. The default registry loads
those four manifests and wraps them in `DeclaredEhrConnector`. Plugin
`tool_definitions()`, `call()`, allowlists, and receipts are unchanged.

## Fail-closed rules

1. **Writes.** `refuse_write` and `assert_not_write_action` always raise
   `EhrWriteRefused`. Manifests may not set `writes_supported=True`.
2. **Production.** `allow_target("production")` raises `EhrTargetRefused` unless
   the manifest claims `production_supported` **and** a C14 `ProductionGate`
   returns true. Today's manifests all set `production_supported=False`, so
   production is refused even if a gate object is passed.
3. **Sandbox.** `allow_target("sandbox")` succeeds only when
   `sandbox_supported` is true. Atlas.md declares sandbox unsupported because
   no vendor sandbox contract is verified in this repository.
4. **Reads.** `allow_read` checks the target gate, then that the resource is in
   `readable_resources`. It does not call a vendor and does not open a network
   connection.

## Hook points (not built here)

| Ticket | Protocol | When it is called |
| --- | --- | --- |
| C14 | `ProductionGate` | Optional argument to `allow_target` / `allow_read` |
| C6 | `PracticeScopeConfig` | Optional argument to `allow_read` when a practice ref is in play |
| C6 | `PhiFreeReadAudit` | Optional argument to `allow_read`; records allowed or refused outcomes without chart payloads |
| C2 | `BackendAuthProvider` | Slot on `DeclaredEhrConnector.auth_provider` for SMART backend-services JWT |
| C3 | `SecretResolver` | Slot on `DeclaredEhrConnector.secret_resolver` for Key Vault (or equivalent) |
| C4 | `FhirReadClient` | Slot on `DeclaredEhrConnector.fhir_read_client` for a FHIR R4 read client |

C2 is expected to branch from this contract's PR head. Keep this interface
small: do not fold auth minting, secret storage, FHIR transport, production
enablement, or audit persistence into this package.

## Declared vendor capabilities

| Vendor | Readable resources | Auth styles | Sandbox | Production |
| --- | --- | --- | --- | --- |
| athena | appointments, medications, allergies, visit_link_status | cosmas_session, athena_platform_bearer | yes (preview maps to sandbox class) | refused |
| elation | appointments, problems, medications, labs | cosmas_session, oauth2_client_credentials | yes | refused |
| tebra | appointments, visit, patients, medications | cosmas_session, tebra_soap_customer_key, tebra_fhir_bearer | yes | refused |
| atlas_md | *(none)* | unverified | no | refused |

Every manifest lists write-class actions under `unsupported_actions`, plus
vendor-specific gaps (for example Tebra medication pagination and Atlas.md
reads). See each plugin's `EHR_CAPABILITY` constant for the exact set.

## How to use

```python
from cosmas_os.plugins.ehr import build_default_registry

registry = build_default_registry()
athena = registry.require("athena")
athena.allow_read("appointments", target="sandbox")  # ok
athena.refuse_write("prescribe")  # always raises EhrWriteRefused
athena.allow_target("production")  # raises EhrTargetRefused
```

Synthetic data only. Tests must not make network calls or load secrets.
