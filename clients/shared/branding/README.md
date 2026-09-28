# CosmaBot app identity

Owner-supplied `cosmabot-identity-pack.zip`, September 28, 2026. The rounded
champagne-gold C forms a smiling face on the Scribe teal (`#146F6C`) to navy
(`#17273C`) background. `cosmabot-c-face.svg` is the supplied editable master.

- `AppIcon.appiconset`: opaque 1024-pixel square for iOS to mask. The Apple
  composer replaces the inherited icon catalog only in its new shell copy.
- `CosmaBot.icns`: supplied macOS icon with platform inset and rounded corners.
  The desktop packager copies it into Resources and sets `CFBundleIconFile`.

Operational builds display **CosmaBot**. Bundle identifiers, sign-in callbacks,
keychain groups, and the existing `CosmasOS Beta` storage directory are stable;
the display name is not a data migration. Workspace colors and individual bot
portraits remain separate from this app identity.

Rebuild and sign new candidates through the normal native packaging process.
Do not patch icons into existing signed apps.
