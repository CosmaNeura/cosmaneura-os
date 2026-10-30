# Preserved local UI changes

These are recovery inputs, not a second app workspace. They have not been
applied, tested or released by this consolidation. Their authorship is unknown.
The original checkouts were left unchanged.

- `provider-portal-ui.patch`: exact full-index tracked diff for 17 files against
  released source `0e70fe6a802ab30362ffb77e8cb8538f7123bc1c`.
- `provider-portal-untracked/web/src/`: three new files captured alongside that
  diff: ProviderConnectionPortal component, test and stylesheet.
- `connector-search-aliases.unreviewed.patch`: separate SettingsHub search
  aliases for Google Workspace/G Suite and Microsoft 365/Office 365.
- `MANIFEST.json`: source checkout, paths, capture consistency and file hashes.

Reconcile on a dedicated feature branch from current main. First compare the
patch against its recorded base and newer main changes, then use three-way
application if appropriate. Copy the three new files only as part of that
reviewed feature change. Both patches touch SettingsHub; applying them blindly
can lose either change. Preserve the recovery inputs as captured evidence.

The old Core API preparation and unfinished host helpers were deliberately
excluded from runtime source. They remain in the private handoff for historical
recovery, subject to the owner's separate application boundary.
