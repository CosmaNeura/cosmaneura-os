# Explicit Microsoft work/school authority

Source base: `c4d9b75019efd09257c78b826280c8becf381e3d`.

`MICROSOFT_CONNECTION_TENANT_ID` retains its blank default and exact fixed-tenant
GUID behavior. The new explicit value `organizations` selects Microsoft's
work/school multitenant authorization and token endpoints. `common`, `consumers`,
authority URLs, case variants and path/query suffixes remain rejected. The public
operational and standalone preparation receipts require an Entra confidential web
app with `signInAudience=AzureADMultipleOrgs` for this mode and report no provider
registration or account consent performed.

The same selection passes through the standalone settings, adapter, operational
bindings, renderer response validator, desktop/Apple preparation argument
validator, desktop packaging gates and owned native consent policies. Callback,
return origin, current session/trusted click, query-field set, S256 PKCE, state,
delegated read scopes, durable exchange, owner/account selection and AES-GCM
custody are unchanged. The existing six-value configuration digest already binds
the authority. Switching between a GUID and `organizations` cannot reuse an
installed service's old connection and requires explicit reconnection.

There is no locked fixed-tenant-only product decision: the previous Microsoft
profile documented that implementation limit. This changes provider account
admission while preserving one Org/Box and the current human membership boundary;
it does not introduce a shared multi-Org runtime.

`clients/*` remains the implementation owner. Only the owned Microsoft native
policy evolves; its new live-source SHA pin supplements the existing frozen
provenance. `apps/capture`, its provenance, all retained upstream source/helper
inputs, PR297 and held1121 inputs are unchanged. No native snapshot, source
composition, SDK/build/signing, account, model, secret, role, registration,
installed configuration or active runtime is changed.

The modified owned native initialization means retained signed1120/helper,
held e23, and the retained 84-source byte proof cannot be reused as qualification
for `organizations`. Their existing hold inputs and the 23-helper inputs are
unchanged; a future native source/build/release must be reviewed independently.

Required cases are added to existing CI test locations for GUID/default
preservation, organizations consent/start-response acceptance, forbidden
authorities, unchanged native consent fences, authority-change custody refusal,
and honest multitenant registration preparation. No tests, builds, renderer,
compose, signing, installation, publication or deployment were run. CI and actual
Entra/admin consent, callback operation and a separately reviewed future native
build remain unqualified.
