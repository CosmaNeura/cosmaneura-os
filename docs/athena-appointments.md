# Athena appointments in the connected workspace

The existing signed `POST /connections/cosmaneura/read` route accepts
`athena_connection` and `athena_appointments`. Enable the default-off
`WORKSPACE_ATHENA_CONNECTION_ENABLED` only with a complete authenticated Core
connection. The shared web/Apple/desktop bundle also requires
`VITE_ATHENA_CONNECTION_ENABLED=true` and the existing Core/workspace flags.
The public example configurations leave these flags off.

The client checks the practice's reviewed Athena schedule, then explicitly reads
a date range of at most 31 inclusive days. Readiness and a successful schedule
read are different states. Times retain the source department's local calendar
components and IANA zone; cancelled appointments remain labelled cancelled.
Page size, total, next offset and truncation come from the bounded Core receiver.
Patient names and opening a clinical notebook from Athena remain unavailable.

The OS sends the current human bearer only to its pinned Core origin. Current
local identity and the reviewed Core account are rechecked before and after the
remote request. Core independently resolves its current actor, tenant, practice
and provider and selects a reviewed schedule profile. Athena credentials stay
in Core. Neither the renderer nor OS supplies vendor practice/provider IDs,
follows vendor URLs, stores appointment observations or creates Core records.
Responses require the current nonce, identity/account digests, source hashes,
date window, bounded pagination, and a fresh observation time.

This version needs no schema change. To disable Athena reads, turn off its OS
flag and omit the client flag on a later build. Keep W42's privacy-aware Core
reference readers and schema; they must not be rolled back after private rows
have been created. Access loss clears the connected view without deleting work.

The September 23 W46 trial used real local OS/Core HTTP, ordinary database
migrations and invented signed identities and Athena transport responses.
Desktop and phone browser layouts passed. It does not establish real Clerk,
vendor service, TLS, installed native, provider, or deployment acceptance.
Practice service-app activation, supported provider onboarding, patient identity
correspondence and real-service qualification remain required before clinical use.
