# Recorded release state — October 30, 2026

This ledger summarizes the last verified October 29 checkpoint. No hosted
runtime, Apple session or phone was inspected again for source consolidation.

| Item | Exact checkpoint | Qualification limit |
| --- | --- | --- |
| Released source | `0e70fe6a802ab30362ffb77e8cb8538f7123bc1c` | PR222 merged as `cc3111cc271a848224b5c30c7ed7734879e1699c`; recorded source/main CI passed |
| Development main at capture | `9b4b3d1d33e68985b33b66597bde5009c8fa87fa` | Newer source, not the source identity of the 1107 binaries |
| iPhone/macOS version | `0.1.147 (1107)` | Signed iPhone upload and notarized Mac artifact recorded |
| TestFlight | 1107 processed and Testing in CosmaBot Beta | Physical iPhone 1107 installation was not directly verified; last direct phone check was 1106 |
| Local Mac app | Last directly verified native desktop was 1105 | ASC 1107 install telemetry does not prove the local native app was replaced |
| Hosted release | `release-r6r1` activation/trial/verification passed October 29 | Web advanced to 1107; API reused R5 source `b770fe05f339e15c681a0df2b4b4b329e47d770d`; no data/schema/identity change |
| Broad goal | Paused after selected release and Cursor handoff milestone | Remaining beta gates are not marked complete |

## Stable private release package

`/Users/jw/Desktop/Cosmas/CosmaBot-Cursor-Handoff-20261029-Final.zip`

SHA-256: `17dc3e1c8b9adb41613d53d35ec85aa743e9824f0c916e6e0fa926cc953e0b9f`.
The ZIP is immutable release/recovery evidence. Older expanded October 29
handoff folders reflect the initial checkpoint and are not this final package
or a current development workspace.

Local release artifacts and retained public build inputs are also under the
Git-ignored `.local-release/` directory on John's canonical workspace. They
are not available to a cloud agent merely by cloning Git. Credentials, private
keys and live operational configuration do not belong in Git. A future build
must select its public profile explicitly rather than reusing settings blindly.

| Released artifact | SHA-256 |
| --- | --- |
| `CosmaBot-0.1.147-1107-AppStore.ipa` | `264aa364f7abc6d9dd546d9cb5bb491daa75a29e243ebc2f6e2814291abdda84` |
| `CosmaBot-0.1.147-1107-notarized.zip` | `068eea306d2a615906f9902efb11def6f74dccf1429792bc60155f1a2c6309d9` |
| `cosmabot-web-0e70fe6-0.1.147-1107.tar.gz` | `bdaa33923211f32a776c2d6682879eae650b40123f84efed8c9af181279a37f7` |

Hosted R6r1 recorded plan SHA-256:
`f15252082b51f46948ef75f7c99a2b171753f87e169d4c05473f8a9011d5a3de`.
Recorded manifest SHA-256:
`cc9e549948c051bb760c68f1dc27137b06010513e6f4509f109842b4b5cf9849`.
R6's initial port-wait failure was recovered; R6r1 contains the reviewed bounded
wait. The final private package contains the stage/trial/verification receipts.
