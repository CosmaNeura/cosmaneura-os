# Installed portal operations

The ordinary app can install named portal integrations for reviewed document
uploads, referral submissions and exact-reference status reads. The existing
portal mapping and work screens are reused. This release does not bundle a real
vendor adapter: each provider requires its own documented contract, typed request
encoder, receipt parser, credentials and service acceptance.

Before starting the API, call `configure_portal_services(app, profile)` with a
`PortalServiceProfile` from `cosmas_os.adapters.portal_services`. The profile holds:

- Explicit `Installation` records: tenant/owner/account selection, fixed
  `PortalProfile` with documentation/contract hashes, supported capabilities,
  exact HTTPS origins and routes, and a display label.
- One adapter factory per named portal. A factory receives `PortalAdapterContext`
  and returns an async context manager that yields the named implementation.
  Entering the factory only constructs resources; it must not contact a provider.
  Exiting closes its HTTP/SDK resources. Catalog reads never call the factory.
- An async credential provider and verified private artifact store. Credentials
  must carry the exact selection commitment and credential reference. A catalog
  may be installed without credentials for setup-only use.

The adapter must use `context.credentials(selection)` and recheck
`context.identity_current()` immediately before each provider action. The credential
wrapper only serves the current invocation's exact installed selection, rechecks
current request/record authority before and after lookup, and refuses changed
credentials. `context.deadline` is the whole-operation monotonic deadline, including
factory creation. Use existing bounded transport patterns; do not add automatic
write retries, arbitrary origins, browser actions or generic custom-API endpoints.

Real provider profiles require explicit `allow_live_profiles=True` and the
authenticated `early_adopter_beta` deployment profile. The default remains false.
Synthetic profiles must remain sandbox-only with their reserved invented origins.
The UI distinguishes local synthetic tests, provider sandboxes and production
accounts. The capability/selection review hash includes the displayed environment.
Legacy `confirm_local_activation` names the local mapping activation in the wire
contract; activation never sends to the provider. Each work item still needs its
own payload review and approval before a send.

Set `PORTAL_SETUP_ENABLED`, `PORTAL_WORK_ENABLED` and, separately,
`PORTAL_IO_ENABLED` as appropriate for the reviewed installation. They default off.
The ordinary startup installs both setup/work catalogs and the per-request executor.
Disabling IO prevents new adapter/credential dispatch while existing receipts
remain readable. Hot-swapping an installed profile is refused; restart with reviewed
configuration. Changed profile/configuration hashes require mapping review again.

Each operation retains a once-ever claim and exact result receipt. HTTP cancellation
does not replay it or discard an already received result. Private settlement has a
separate five-second database budget and cannot perform provider IO. Shutdown blocks
new execution, drains owned operations within their configured deadlines, and
finishes adapter cleanup. Unconfirmed outcomes remain available for human review.

Portal composition itself introduced no schema change. Current API and worker
readiness follows the subsequent Google connection migration `e5917a2c64bd`.

W56 qualification uses normal application startup, actual Clerk JWT verification
with invented RSA/JWKS, ordinary PostgreSQL migrations and real private PDF custody.
Provider operations are injected. Production-profile admission and the production
review screen are checked without provider calls. Actual vendor operation, native
device use, hosting and release acceptance remain separate. Athena remains strictly
read-only and is not registered as a portal write integration.
