# Configure existing account and managed-service connections

The operational startup preparer accepts `--connections` pointing to a reviewed
file shaped like `operational-connectors.example.json`. All example values are
invented. Each `google`, `microsoft` or `managed_services` section may be `null`.
Omitting the option preserves the original baseline startup behavior.

```sh
python3 -B scripts/prepare-operational-startup.py \
  --identity /absolute/path/to/reviewed-desktop-identity.json \
  --bindings /absolute/path/to/reviewed-service-bindings.json \
  --connections /absolute/path/to/reviewed-connectors.json \
  --output /absolute/path/to/new-startup-directory
```

This uses the existing Google/Microsoft account implementations, adapted from
Activepieces community OAuth/read patterns, and existing managed-service
adapters. It adds no connector framework or subscription. The source attribution
remains in the selected OS service's Google/Microsoft connection docs and retained
MIT license.

Google uses a separate confidential web client from Scheduling staff login and
Calendar. Normal sign-in requests `openid email gmail.metadata` plus
`https://www.googleapis.com/auth/calendar.events.readonly`, matching the existing
adapter. Metadata-only legacy grants remain accepted; they cannot read calendar
summaries until the human adds calendar access. Microsoft uses one configured work/school tenant,
requests `offline_access User.Read Mail.Read Calendars.Read`, and displays bounded
email/calendar summaries. The flows retain explicit account consent, PKCE,
server-side encrypted token custody, current member checks and disconnect behavior.
Neither input accepts custom scopes or endpoints.

The Google section optionally accepts this closed feature selection:

```json
"enabled": {"full_message": false, "calendar": false}
```

Omitting `enabled` preserves both source features as false. If present, both
fields must be literal booleans. They select `WORKSPACE_GOOGLE_MESSAGE_ENABLED`
and `WORKSPACE_GOOGLE_CALENDAR_ENABLED` in the complete service and Athena maps.
They enable the existing selected-source interfaces, not account grants or human
review. Matching client feature flags and reviewed public OAuth inputs still
require an appropriate web/native build. Calendar summaries remain bounded to
the primary calendar's next seven days; selected full email remains bounded to
5,000 characters with unsupported content withheld for human handling.

`provider-registration.json` records normal sign-in scopes, accepted legacy
scopes and the selected source features separately. Only explicit
`full_message:true` adds `full_message_consent_scopes` with `gmail.readonly` for
the separate human full-message consent flow. Normal sign-in does not acquire
that scope. Neither feature selection performs consent, source review, a read,
email sending or calendar mutation.

Each OAuth client secret and 32-byte custody key needs a separate immutable Key
Vault reference. Supply the actual values using the existing secret ownership
process. References are checked for separation; the preparer never reads secret
contents. `provider-registration.json` records the exact API callbacks and
existing scopes for provider configuration. It does not register an application
or perform consent. Pass the generated `native-connection-arguments.json` fields
to the existing desktop/Apple preparation options along with the generated
identity. Their names correspond to CLI options with underscores changed to
hyphens. Empty optional sections leave the respective native handoff unset.

The managed-services section supplies the existing account manifest's immutable
secret version and exact content SHA256, plus its named
`COSMAS_MANAGED_SECRET_*` references. The selected OS runtime validates the actual
manifest, Box, installed accounts, credential hashes, route bindings and private
storage when it loads. This preparer validates references only; it cannot assert
that a referenced private document exists or has been accepted. The manifest must
fit the Key Vault secret size limit. No account manifest is created, fetched or
installed by preparation, and no account review, local activation or action
approval is performed.

The four managed I/O/event values are explicit and remain false in the example.
Reviewed account setup can be configured before execution. Selecting a flag in
these inputs still requires all existing runtime account/action approvals;
preparation itself performs no provider operation. Deferred Spruce and portal
activation is not changed. Portal transport remains a separate integration.

With this option, preparation produces thirteen top-level files plus eight client
files. It updates complete feature/public/secret maps so Terraform's replacement
semantics preserve all baseline values. The separate Athena read-only feature
file retains the selected account features. Athena remains off until its own
read-only layer and accepted private profile are supplied. Research I/O remains
separate. Current binaries need actual public-value rebuilds and service/device
acceptance before release; no build, signing, deployment or provider call occurs.
