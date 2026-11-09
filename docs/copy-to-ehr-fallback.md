# Copy offer when a read fails

Tonight for existing live users: nothing changes. `copy_to_ehr_fallback_enabled`
defaults to off, and nothing is deployed.

When the flag is later turned on, an adapter error or a disconnect during a
visit read marks that visit `not_sent_copy_instead`. The visit view then shows
"not sent, Copy to EHR". The clinician can see the note was not sent and can
copy it by hand. The visit and the note keep moving. This path never blocks
them and never delays them.

The vendor id goes through `copy_profile_for_vendor`. If nothing matches, the
copy profile is `generic`. `plugins/ehr` and `VendorRegistry` stay unchanged.

The audit event is `copy_to_ehr.fallback_shown`. It carries metadata only
(event, profile id, outcome, correlation id). Note text never goes into the
audit or the log. If the offer itself fails, the read still returns its
original value or its original error, and the failure is logged as metadata
only.
