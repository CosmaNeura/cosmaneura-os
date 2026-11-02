# Tebra reads in the CosmaBot connectors plugin

The CosmaBot connectors plugin exposes four read-only Tebra tools. Each one calls the existing signed route `POST /connections/ehr/reads` through the current CosmaBot session. The plugin does not take a token, choose another record system, or send a free-form query.

Appointments and the verified visit use the practice connection. Authorized patients and medication records use the Tebra FHIR connection. These tools do not prescribe, sign, book, or change Tebra. Merging this change does not deploy it. People using CosmaBot today do not see these tools until a release ships the plugin.

## Tools

| Tool | What it asks CosmaBot to read | What a successful result returns |
| --- | --- | --- |
| `tebra_read_appointments` | One date window, at most seven days | One page of appointments: time, status, and whether the row can be selected. Practice name and timezone. The saved observation id and hash. No patient names and no vendor ids. |
| `tebra_read_visit` | One selected appointment, plus the surname and birth date that verification already requires | That one visit: time, status, and the patient name and birth date on the visit. This is not a chart search. |
| `tebra_read_authorized_patients` | The patients already granted for one encounter | Names and birth dates for those authorized patients, plus the handle needed to read medications. Not a complete patient list, and not a search. |
| `tebra_read_medications` | One authorized patient already returned by the patient list | One page of medication records: name, status, intent, authored date, the do-not-perform flag, and recorded direction text. The patient name and birth date. Vendor record ids and the raw record JSON stay on the CosmaBot read and are not copied here. |

A successful result is one page, or one verified visit. Appointments are returned rows only; Tebra does not say whether a later page exists, and the tool does not ask. When a medication page says more rows exist, the message says so. The tool does not ask for the next page and does not accept a cursor.

An empty page is still a successful read. The message says that an empty page does not mean the chart is empty.

## What the person sees

Every result has a `state` and a plain `message`.

| State | When it happens | Message |
| --- | --- | --- |
| `ready` | The connected practice returned one page or one visit | The page sentence, including whether more medication rows may exist |
| `not_connected` | Tebra is not set up for this sign-in, or setup is still required | Tebra is not connected. Connect Tebra for this practice in CosmaBot, then try this read again. |
| `unsupported` | This CosmaBot workspace does not offer that Tebra read | This Tebra read is not supported. |
| `wrong_practice` | The request names a different connection than the one on this sign-in | That request is for a different practice than the Tebra account connected to this sign-in. |
| `expired` | Access was revoked, the binding changed, or the account can no longer open the read | Tebra access expired or was revoked. Reconnect Tebra in CosmaBot before reading again. |
| `malformed` | The response was not the expected page | Tebra returned a response CosmaBot could not read. No chart data is shown. |
| `timeout` | The read timed out or the result was not confirmed | The Tebra read timed out before a result was confirmed. Repeat this same request to recover it. A different request is not sent automatically. |
| `stale` | The Tebra account or the CosmaBot sign-in changed before the page could be shown | The Tebra account changed while this was being read. The result was discarded. Check the connected practice and read again. |
| `sign_in` | The CosmaBot session is signed out | Sign in to CosmaBot again before reading Tebra. |

Chart rows are returned only for `ready`. A stale, malformed, expired, or wrong-practice result does not include them.

The tools are marked read-only (`readOnlyHint` true, `destructiveHint` false).

## Reads that stay unsupported

These are not tools. Each one would need a new closed action on the existing EHR read route before a tool could call it. This change does not add that action.

| Read | Why it is not a tool | API change that would be needed |
| --- | --- | --- |
| Patient search that is not tied to one selected appointment | `find_patients` runs only inside visit verification, which `tebra_read_visit` already calls | A closed action that searches patients without an appointment |
| The next medication page | The current medication route returns one page and does not accept a cursor | A closed action that returns the following page for a saved observation |
| Problems, allergies, labs, and a SOAP medication list | Those actions are not Tebra routes. Problem and medication commands reject provider `tebra` | New closed Tebra commands and handlers |
