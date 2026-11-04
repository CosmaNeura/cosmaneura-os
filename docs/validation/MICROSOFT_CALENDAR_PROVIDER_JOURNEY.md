# Outlook Calendar: reviewed visit source

A provider opens **Review Outlook Calendar**, checks the connected account, loads a bounded seven-day view and selects one event. CosmaBot shows that event’s exact title, UTC times, cancellation marker and observation window. The provider chooses an existing linked visit, confirms all three review checks and explicitly saves the summary. **Ask Chief about this calendar summary** adds source instructions to the current Chief question without sending it or replacing an unsent question. The clinical note is unchanged.

The API reserves one immutable read before the existing Graph `GET /v1.0/me/calendarView`, using the existing `Calendars.Read` grant. It reads at most 25 events, reports incomplete coverage and never follows an additional page. It performs no calendar mutation, external send or automatic patient matching. Graph’s opaque event identifiers and explicit UTC instants are preserved, including all-day events.

The source is accepted only for the authenticated actor and Box, their current Microsoft account/grant, the exact observation and event hashes, the existing linked visit and its current revision. Database constraints bind the review to its entry. Retries reuse the exact request and result; resolving a lost read does not repeat Graph. Revoked, superseded, expired or changed sources are withheld from display and Chief context. Account changes and native browser handoffs remain blocked while calendar work is unresolved.

The private encrypted account journal retains selected events and exact unconfirmed requests. Unknown save outcomes remain pending; they are not silently retried under a new key. Older/unavailable APIs offer a clear refusal and retain the conversation draft.

## Focused synthetic qualification

- `tests/integration/test_microsoft_calendar.py`: exact selected source reaches real Chief admission/claim context; event/hash/revision/grant/account/acknowledgement rejection; exact save retry and read resolution; source withholding; database forgery/immutability; cross-Box, owner and workspace rejection. Real temporary local PostgreSQL and additive migrations; invented provider port, no external model/provider call.
- `tests/unit/test_microsoft_calendar_contract.py`: closed requests, explicit review acknowledgements, server-owned fields, exact hashes and expiry, all-day UTC instants and opaque identifier bounds.
- `tests/unit/test_microsoft_calendar_adapter.py`: real adapter with HTTP MockTransport; exactly one bounded existing calendarView GET, UTC request, no page follow/write, malformed response and changed grant rejection.
- `MessagesMicrosoftCalendarJourney.test.tsx`: fully mounted selection → exact review → save → Chief preparation with unsent question retained; unavailable older service → no load/save and retained draft. This uses a private invented fixture, not a live provider/API qualification.
- Existing Microsoft account-lock cases now also cover calendar work, including native handoff suppression and release recovery. `session/composer.test.ts` confirms only current reviewed Outlook calendar evidence enables saved Chief context.
- Affected Outlook mail, Google Calendar and Settings task journeys passed; the desktop boundary has exact route/header/body/response limits and late-identity rejection.

The durable source-review receipt lists actual commands, results and earlier failed fixture/setup attempts. No required CI job has been run or waived in this local feature lane.

## Release limits

This is a source candidate, not an activated provider connection or shipped binary. `workspace_microsoft_calendar_enabled` defaults off and still requires Microsoft connection, authenticated workspace and Clerk identity. The client reuses the existing reviewed `VITE_MICROSOFT_MESSAGE_ENABLED` plus Microsoft connection gate; it introduces no new native build-profile gate and still requires a matching server calendar status before any read/save.

The independent-beta native profile keeps Microsoft dark by default. This consolidated source adds an explicit Microsoft capability selection and validates the existing tenant/client, exact owned callback/return origins and protected custody key in `standalone_clerk_synthetic`. Only matching native inputs and the exact protected secret pair admit the existing OAuth broker. No provider settings, scopes, credentials or deployed beta inputs were changed here.

The additive three-table migration `cc68d2f1a903` follows the restored deployed `bb57e3d10c964` schema history from PR295. Published migrations remain unchanged, and runtime/release metadata select the new additive revision. This source chain is not a qualification of the hosted R10 database. Matching API, schema, compiled provider gates and live grant checks must all pass before claiming the new action is operational. Core and separate Scribe remain untouched.
