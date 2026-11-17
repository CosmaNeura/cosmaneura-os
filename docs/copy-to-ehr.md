# Copy to EHR (clipboard paste)

Tonight for existing live users: nothing changes. Every flag defaults to
`False`, and nothing is deployed.

This feature helps a clinician copy a reviewed CosmaBot note into their chart
by hand. The clinician always presses Paste. CosmaBot never types into the
chart, never opens the vendor screen, and never carries note text to another
device.

## Flags (default off)

| Flag | Owner | Meaning when later turned on |
| --- | --- | --- |
| `copy_to_ehr_enabled` | A | Export mapping + GET package route |
| `copy_to_ehr_remote_enabled` | C | Phone highlight remote (no note text in messages) |
| `copy_to_ehr_fallback_enabled` | D | Show the copy strip when a visit mark says copy instead |

## Profiles

Copy profiles live in `src/cosmas_os/application/ehr_export/` as a plain dict.
They reference existing EHR vendor ids from `CapabilityManifest.vendor_id`
(`atlas_md`, and later `athena` / `elation` / `tebra`) plus one extra literal
`generic`. Read connectors and `VendorRegistry` are untouched.

`copy_profile_for_vendor(vendor_id)` returns the matching copy profile, or
`generic` when none matches. Track D uses that helper.

## Visit status (Track D)

`VisitCopyToEhrStatus` includes `not_sent_copy_instead`. Track D sets that on
a visit when the note was not sent and the clinician should copy instead. It
must be visible, must never be silent, and must never block the visit.

## Route

`GET /api/copy-to-ehr/drafts/{draft_id}?profile=...&revision=...`

- `404` when `copy_to_ehr_enabled` is off (or the draft/profile is missing)
- `409` when `revision` does not match the draft revision
- Response is package JSON including rendered `full_note`
- Extras (`patient_instructions`, `orders`) stay out of the full note

## Audit

Events: `copy_to_ehr.opened|copied|cleared|done|blocked|fallback_shown`.
Metadata only (`event`, `profile_id`, `outcome`, `duration_ms`, correlation
id). Note text never goes into logs or audit.

## Package

`src/cosmas_os/application/ehr_export/` owns `EhrExportProfile`,
`ExportSection`, `ExportPackage`, `build_export_package`, `render_full_note`,
and `render_section`. Plain text only, no leading `#`, bullets normalised.
