# Athena reads in the CosmaBot connectors plugin

The CosmaBot connectors plugin exposes four read-only athenaOne tools. Each one calls an existing signed CosmaBot route through the current session. The plugin does not take a token, choose another EHR, or send a free-form query.

These tools do not prescribe, sign, book, or change the Athena chart. Merging this change does not deploy it. People using CosmaBot today do not see these tools until a release ships the plugin.

The Elation read-only tools are already registered. These four athenaOne tools are registered after them.

## Tools

| Tool | Route it calls | What a successful result returns |
| --- | --- | --- |
| `athena_read_appointments` | `POST /connections/cosmaneura/read` with `athena_appointments` | One page of appointments: local start, department timezone, duration, and a plain status (booked, checked in, checked out, charge entered, or cancelled). Practice and department names. No patient names and no vendor ids. |
| `athena_read_medications` | `POST /connections/ehr/reads` with `core_medications` | The returned medication section for one authorized patient: medication name, status, route, directions, the recorded quantity spelling, and whether it was marked discontinued. The patient name and birth date already on that read. |
| `athena_read_allergies` | `POST /connections/ehr/reads` with `core_allergies` | The returned allergy section for one authorized patient: allergen name, criticality, onset, deactivation, note, and reaction name and severity. The no-known-drug-allergies statement is kept separate from the list. |
| `athena_read_visit_link_status` | `POST /connections/cosmaneura/read` with `athena_visit_status` | The status of one saved visit link: linked, removed, not found, or still needs review. It does not link, unlink, or open a visit. |

Appointments are the first page only (`offset` 0). When Athena says more rows exist, the message says more may be available. The tool does not ask for the next page and does not accept an offset or a cursor.

Medication and allergy reads are one returned section. Those Athena chart routes do not offer a next page. The message says this is not a complete chart. An empty page does not mean the chart is empty. A no-known-drug-allergies or no-medications-reported statement stays visible beside any rows.

Visit-link status is one saved request, not a list.

## What the person sees

Every result has a `state` and a plain `message`.

| State | When it happens | Message |
| --- | --- | --- |
| `ready` | The connected practice returned one page or one link status | The page or status sentence, including whether more appointment rows may exist |
| `not_connected` | Athena is not set up for this sign-in, or the schedule route says a Core account is still required | Athena is not connected. Connect Athena for this practice in CosmaBot, then try this read again. |
| `unsupported` | This CosmaBot workspace does not offer that Athena read | This Athena read is not supported. |
| `wrong_practice` | The request names a different connection than the one on this sign-in | That request is for a different practice than the Athena account connected to this sign-in. |
| `expired` | Access was revoked, the binding changed, the account can no longer open the read, or a medication or allergy grant can no longer be opened | Athena access expired or was revoked. Reconnect Athena in CosmaBot before reading again. |
| `malformed` | The response was not the expected page | Athena returned a response CosmaBot could not read. No chart data is shown. |
| `timeout` | The read timed out or the result was not confirmed | The Athena read timed out before a result was confirmed. Repeat this same request to recover it. A different request is not sent automatically. |
| `stale` | The Athena account or the CosmaBot sign-in changed before the page could be shown | The Athena account changed while this was being read. The result was discarded. Check the connected practice and read again. |
| `sign_in` | The CosmaBot session is signed out | Sign in to CosmaBot again before reading Athena. |

Chart rows are returned only for `ready`. A stale, malformed, expired, or wrong-practice result does not include them. An expired or revoked result does not retry the read.

The tools are marked read-only (`readOnlyHint` true, `destructiveHint` false).

## Routes already in the product

No API change was required.

- Medications and allergies are already on `POST /connections/ehr/reads` (`status`, `core_medications`, `core_allergies`).
- Appointments and visit-link status are not on that EHR route. They are already on `POST /connections/cosmaneura/read` (`athena_connection`, `athena_appointments`, `athena_visit_status`).

The schedule route uses one 404 detail, `core_connection_unavailable`, both when Core is not offered and when the Athena schedule or visit-link flag is off. The plugin shows that as unsupported. A connected Core account that is missing is already a different code, `core_connection_required`, and the plugin shows that as not connected. Splitting the 404 into `athena_schedule_unavailable` and `athena_visit_link_unavailable` would only change the message when the whole Core connection feature is off. That split is not required for these tools.

Medication and allergy chart routes document no next page. The plugin does not invent one.
