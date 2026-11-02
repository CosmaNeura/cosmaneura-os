# Atlas.md and the CosmaBot connectors plugin

CosmaBot cannot read Atlas.md through this plugin. A search of `src/`, `docs/`, and `tests/` found no Atlas.md read route, HTTP client, OAuth client, or connector adapter. This page says what the repository does contain. It does not add an endpoint.

The plugin tools below are read-only (`readOnlyHint` true, `destructiveHint` false). Each one takes no arguments. Calling one does not contact Atlas.md, CosmaBot's EHR read route, or any other address. Merging this change does not deploy it. People using CosmaBot today do not see these tools until a release ships the plugin.

## What a read returns

| Tool | Arguments | Result |
| --- | --- | --- |
| `atlas_md_read_appointments` | None | `state` is `unsupported`. The message is "This Atlas.md read is not supported yet." |
| `atlas_md_read_patients` | None | The same unsupported message. |

These names are CosmaBot's way of answering an appointment read and a patient read. They are not Atlas.md API operations, and this repository does not document Atlas.md resources under these names. A token, cursor, query, or any other argument is rejected. No chart rows are returned. There is no ready page, because no read is attempted.

Other chart information, including problems, medications, and labs, has no Atlas.md read in this repository either. Those are not separate tools, and they are not available by passing a free-form argument.

## Staff-supplied calendar file

The repository does include a calendar-file import. A person can upload a bounded `.ics` file and report the source as `atlas_md` or `other_calendar`.

- `src/cosmas_os/ports/calendar_imports.py` allows those two reported sources.
- `src/cosmas_os/application/calendar_imports.py` stores the label in the saved summary as "Source reported by user: Atlas.md" when the choice is `atlas_md`.
- That same summary says: "This staff-supplied calendar summary does not verify patient or chart identity, current availability, or a booking."
- `tests/unit/test_calendar_import_contract.py` checks that the Atlas.md wording is the self-reported label.

`docs/beta/EHR_CONNECTOR_WORKSTREAM_20261025.md` says Atlas.md is a source reported by the user. That flow does not connect to Atlas.md, and it does not verify patient identity, availability, or a booking. The same note says compatibility with an actual Atlas-produced synthetic export remains unverified. The plugin does not import that file, and this page does not describe the import as a connection to Atlas.md or as synchronization.

## Membership ledger label

`src/cosmas_os/api/membership_work_schemas.py` allows `system_kind` on a reviewed membership ledger proof to be `hint`, `atlas_md`, `practice_owned_ledger`, or `other`. That is a label on a record a person reviewed. No code under `src/` calls Atlas.md to fill it.

## What the docs already say is missing

`docs/beta/EHR_CONNECTOR_WORKSTREAM_20261025.md` says public documentation establishes calendar subscriptions and exports, and that a public practice API, authentication, and sandbox contract has not been verified. It says not to invent endpoints, not to automate the clinician UI, and not to label an imported calendar as a connected EHR account. It says to obtain the supported vendor integration contract before synchronization.

`docs/elation-read-integration.md` says no public Atlas.md practice-write API, OAuth flow, or reusable official SDK was verified. It cites [Atlas.md's calendar help page](https://atlas.md/help/view/working-with-the-calendar-on-a-tablet/) as documentation of calendar subscription support. It says fetching subscription URLs and adapting CSV headers stay outside that milestone. This plugin does not fetch that page or any subscription URL.

## Open questions before a real read

These are gaps the repository already records. They are not an Atlas.md API specification.

1. Which practice read API, authentication method, and sandbox Atlas.md supports. None of those is verified in this repository. Synchronization waits on the vendor integration contract the workstream asks for.
2. A practice-write API, an OAuth flow, and an official SDK are recorded as not verified. A read API is also absent from `src/`. Real reads need that contract before any endpoint is added.
3. The workstream's statement that public documentation establishes calendar subscriptions and exports is not implemented as a fetch. Whether an `.ics` file produced by Atlas.md parses in the staff-supplied importer is unverified.
4. The membership label `atlas_md` has no vendor read behind it. What record a person is classifying is outside this plugin.

Do not invent endpoints to close these gaps.
