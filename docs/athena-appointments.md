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
The schedule projection does not provide patient names. With the separate
visit-link gate enabled, a reviewed match to an existing Core patient/visit can
provide the name and open that visit's existing CosmaBot notebook.

The OS sends the current human bearer only to its pinned Core origin. Current
local identity and the reviewed Core account are rechecked before and after the
remote request. Core independently resolves its current actor, tenant, practice
and provider and selects a reviewed schedule profile. Athena credentials stay
in Core. Neither the renderer nor OS supplies vendor practice/provider IDs,
follows vendor URLs, stores appointment observations or creates Core clinical
records as part of the schedule read.
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

## Shared visit task and durable recovery

The default-off visit-link path additionally requires
`WORKSPACE_ATHENA_VISIT_LINK_ENABLED=true` and
`VITE_ATHENA_VISIT_LINK_ENABLED=true`. Supported JWT clients reach the same
**Find or connect an Athena visit** task from Chief or Connections. Exact
patient/visit matching remains a separate explicit review; it is not inferred
from the schedule's patient reference alone.

The task retains bounded encrypted account-scoped command metadata before a
confirmed link/removal. Reload and native backgrounding preserve the pending
request while hiding patient details. An explicit saved-result check issues only
status with the original command key/hash and a fresh nonce. The recovered
projection must still match the reviewed account, actor, patient and appointment
or exact removal link. A new mutation requires a new reviewed command.

Opening the linked notebook preserves ordinary unfinished-work checks. A clean
open clears the task even when the notebook is already current, and failures
remain visible for an open-only retry. See the
[October 25 connector checkpoint](beta/EHR_CONNECTOR_WORKSTREAM_20261025.md)
for local, Mac Studio and rebuilt-simulator evidence. These tests use invented
services and do not establish live Core/Athena or physical-phone acceptance.
