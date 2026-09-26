# Desktop archive and integrity packaging

The operational Mac build can now be packaged into app.asar with embedded header
integrity and the Scribe Electron fuse policy. The archive includes the entire
workspace, preload, public configuration, source assets and native-helper hash
manifest. Only the native helper .app is unpacked. The main process resolves its
executable from app.asar.unpacked and verifies every file against the protected
manifest before creating a spawn capability. Extra, changed or linked native
files are refused. The existing loose development layout remains supported.

Reused source: Scribe commit fe22a435b6201c2d8013348927ea6a349e0b48c6,
assemble-electron-package.mjs and harden-electron-package.mjs. Their tree,
ASAR/header verification and exact fuse policy are adapted to the CosmasOS native
helper and stable beta identity. Source hashes are recorded under
clients/desktop/release. The existing qualified Electron43.4.1 package is the
input; it is not downloaded or rebuilt. The pinned @electron/asar4.3.0 and
@electron/fuses2.1.3 APIs perform archive creation and fuse writes directly.

First run scripts/prepare-desktop-release-tools.py with --npm-cache pointing to
the content-addressed npm cache and a fresh --output directory. It verifies the
nine exact public packages from Scribe's lock, checks all302 file hashes, and
materializes only those files. It performs no network requests or lifecycle
scripts. Missing cache entries are reported before output is created.

Compose and package the current operational desktop build normally, then record
its exact file inventory using the exported inventory() function. Invoke
scripts/package-desktop-release.mjs with these ordered arguments:

```text
--application /absolute/path/UnsignedBeta.app
--input-manifest /absolute/path/unsigned-package-manifest.json
--tools /absolute/path/prepared-build-tools
--output /absolute/path/ReleaseCandidate.app
```

The input is verified before copying. The output must be fresh and separate.
Electron's existing default-app integrity header is verified against its actual
archive, then that copied default archive is removed and its metadata is replaced
with the new CosmasOS archive binding. Unknown prior integrity entries are refused.
Every archived byte, packed-file block hash, native executable mode and unpacked
file is compared with the input. ElectronAsarIntegrity binds the exact header.
All nine fuse settings are explicit: RunAsNode, NODE_OPTIONS, inspector arguments
and extra file-protocol privileges are disabled; archive-only loading, embedded
integrity, cookie encryption, browser-specific snapshot and Wasm trap handlers are
enabled. Automatic ad-hoc signing is explicitly disabled. The input package and
its files are checked again afterward. A receipt records the exact output and
changed framework; a failed output retains its incomplete marker.

This tool creates an unsigned candidate. It does not use signing keys, notarize,
install, launch, publish an update or authorize distribution. Signing must follow
the archive/fuse changes. Installed Electron/ASAR startup and native login still
require the deferred device acceptance; byte verification does not replace it.
The current iPhone device compiler product is unaffected by this desktop change.
