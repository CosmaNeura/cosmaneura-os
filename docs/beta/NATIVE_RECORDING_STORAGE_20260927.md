# Protected native recording storage

The Apple composition now uses the current secure queue adapter alongside the
native encrypted PCM and custody packages. It preserves the previous app's
device key, `CSQ1` encrypted file format, record revisions and storage directory.
The native recorder and Capacitor storage plugin share one process lock.

Native flow, binding, lease and reservation journals use `cosmas-native-*` keys.
The renderer adapter rejects all read/write/create/CAS/delete operations on that
prefix and filters it from listing. Its bulk clear checks all committed records
under the same lock and rejects without deleting anything when native custody
is present. Encrypted `cosmas-provider-queue:v1` upload records remain accessible
through the existing upload interface. Native recording is not selected by the
recording screen yet.

All eight copied inputs, including the disk-space privacy resource, are bound
by `clients/capture/native-configured/manifest.json` to Scribe commit
`ec511ff1c3b979901e80f5033c1f02a05f65c4b3`. CosmaBot adaptations change native
journal/upload prefixes and add an internal store initializer for isolated tests.
The ordinary device Keychain service/account and directory are unchanged.

Local verification compiles the actual storage sources, uses temporary files
and unique synthetic Keychain items, and cleans them afterward. It covers:

- A full synthetic three-hour visit: 1,080 encrypted packets, 345,647,520 WAV
  bytes, reopening with the original key and sealing the original completion
  intent through the actual native recording owners.
- Record replacement/revision conflicts, ciphertext tampering, backup exclusion,
  storage capacity without key creation, renderer journal denial and clear safety.
- Existing files written by the exact prior app storage implementation at
  `ea7f99d0278a05706531ffb1288cb1df7acf507b`: new code reads without rewriting the
  file or key, and both implementations read subsequent revision updates.

Eight tests pass across the storage and compatibility runs. One iPhone-only
Keychain Data Protection assertion is explicitly skipped on Mac. Its initial
Mac execution returned no iOS accessibility attribute; that is not proof of the
iPhone's protection while locked. The strict iPhone assertion remains in the
test source for device qualification.

The actual unsigned iPhone Release archive also compiles the Capacitor wrapper
and native adapter together. The first archive exposed a missing privacy resource;
the resource is now included and hash-bound before final archive verification.
No app is installed, no existing recording is touched, and no cloud service is
activated by these checks.

Run the local harness with `scripts/test-native-secure-queue.py --output` pointing
to a fresh directory outside the checkout. `--filter LegacyQueueCompatibilityTests`
selects only the prior-app compatibility case. The optional `--scribe-source`
selects the read-only checkout containing the pinned previous implementation.

Next: native account recovery context, retained run/host, recording-screen and
uploader selection, and the Mac live audio/storage adapter. The native host must
honor the source permit's actual position limit; the general PCM library's 2,048
ceiling must not silently replace the currently selected 360-position grant.
