# Elation reads in the CosmaBot connectors plugin

The CosmaBot connectors plugin exposes four read-only Elation tools. Each one calls the existing signed route `POST /connections/ehr/reads` through the current CosmaBot session. The plugin does not take a token, choose another EHR, or send a free-form query.

These tools do not prescribe, sign, book, or change the Elation chart. Merging this change does not deploy it. People using CosmaBot today do not see these tools until a release ships the plugin.

## Tools

| Tool | What it asks CosmaBot to read | What a successful result returns |
| --- | --- | --- |
| `elation_read_appointments` | One date window, at most seven days | One page of appointments: time, status, and whether the row can be selected. Practice name and timezone. The saved observation id and hash. |
| `elation_read_problems` | One already verified visit | One page of problem descriptions, statuses, dates, and verification text. The patient name and birth date already on that visit. |
| `elation_read_medications` | One already verified visit | One page of medication names and the recorded details Elation returned. The patient name and birth date already on that visit. |
| `elation_read_labs` | One already verified visit in one encounter | One page of lab report candidates (titles and dates), not attachment files and not a signed report. |

A successful result is one page. When Elation says more rows exist, the message says more may be available. The tool does not ask for the next page and does not accept a cursor.

An empty page is still a successful read. The message says that an empty page does not mean the chart is empty.

## What the person sees

Every result has a `state` and a plain `message`.

| State | When it happens | Message |
| --- | --- | --- |
| `ready` | The connected practice returned one page | The page sentence, including whether more rows may exist |
| `not_connected` | Elation is not set up for this sign-in, or setup is still required | Elation is not connected. Connect Elation for this practice in CosmaBot, then try this read again. |
| `unsupported` | This CosmaBot workspace does not offer that Elation read | This Elation read is not supported. |
| `wrong_practice` | The request names a different connection than the one on this sign-in | That request is for a different practice than the Elation account connected to this sign-in. |
| `expired` | Access was revoked, the binding changed, or the account can no longer open the read | Elation access expired or was revoked. Reconnect Elation in CosmaBot before reading again. |
| `malformed` | The response was not the expected page | Elation returned a response CosmaBot could not read. No chart data is shown. |
| `timeout` | The read timed out or the result was not confirmed | The Elation read timed out before a result was confirmed. Repeat this same request to recover it. A different request is not sent automatically. |
| `stale` | The Elation account or the CosmaBot sign-in changed before the page could be shown | The Elation account changed while this was being read. The result was discarded. Check the connected practice and read again. |
| `sign_in` | The CosmaBot session is signed out | Sign in to CosmaBot again before reading Elation. |

Chart rows are returned only for `ready`. A stale, malformed, expired, or wrong-practice result does not include them.

The tools are marked read-only (`readOnlyHint` true, `destructiveHint` false).
