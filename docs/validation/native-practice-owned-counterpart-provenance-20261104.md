# Reviewed native practice counterpart provenance

This proposal is based on PR 284 source
`0d2afe6bc99bd72b890fbf5ae3a501ba77ea3280`. The obsolete `ca8ff3a`
backend-1 run failed because the reviewed live `ClerkKitWorkspaceDriver.swift`
counterpart changed while its exact-byte pin still described the prior source.

Root reviewed the production snapshots identified as `6ef` and `520`, integrated
as `9fd4d3d186e95a746e93c33b198cbdfa2b8af1ce` and
`812152b3ce7b92c137601cb89746e72b7930f84a`. These are source review references,
not a claim of live authentication or SDK qualification.

The added `resumeAfterWorkspaceClose` implementation preserves five guards:
the selected-practice runtime must identify the retired source and expected
account; the driver must be retired; no native operation may remain pending;
the same Clerk SDK and configured realm must still match; and the resumed
driver must identify the same expected account. It reuses the existing SDK,
configuration and policy without login, reconfiguration, credential copying or
a new keychain slot. No native production source is changed by this proposal.

All 16 entries in `REVIEWED_PRACTICE_CONNECTION_COUNTERPART_SHA256` were compared
with the complete current live map. Only this existing entry differs:

| Owned counterpart | Previous reviewed SHA-256 | Current reviewed SHA-256 |
| --- | --- | --- |
| `clients/apple/native-auth/Sources/CosmasNativeAuth/ClerkKitWorkspaceDriver.swift` | `2409c3636573890de3c9ba6179ac1b3dfff533a92599e8ddc8d6638b2cf37a10` | `8d90bb1fd7e86a6773b99d4bb560eadfa66f9aaad57b89e2fbefde509392f1a9` |

`NativeWorkspaceAuth.swift` already matches its existing reviewed pin; that
entry and the other 14 matching entries are unchanged. The dictionary keeps
all 16 exact-byte assertions. No wildcard, entry removal, skipped test, xfail
or looser assertion is introduced.

The recovered `apps/capture` tree remains frozen 1107 evidence. Its
`SOURCE_PROVENANCE.json` still has SHA-256
`f1d73c9e7fd9515d7dd16b676f78d1cacd420a63d9f7524fe9444525c9bdf2a3`.
Neither that manifest nor any recovered file is edited. The original recovered
hashes and unqualified status remain enforced independently from the live
owned-source evolution map.

Qualification requires the actual complete provenance module on this proposal,
followed by all 13 CI jobs on the integrated new PR head. This proposal does not
qualify a typed Clerk/UIKit SDK build, live sign-in, a physical phone journey,
signing, installation or release. Those gates remain separate. The previously
delivered 1113 package is preserved; this work does not reserve or publish 1114.

Actual local validation on the proposal: the complete
`tests/unit/test_recovered_capture_provenance.py` module passed **6 tests** with
a fresh owned `--basetemp`, without warnings. The first default-temp invocation
also passed but its automatic housekeeping was denied for unrelated retained
fixtures; the isolated invocation avoided that housekeeping. `git diff --check`
passed. Comparing the test AST after normalizing the one reviewed digest proves
every test body and assertion is unchanged. All 16 live pins now match; the
frozen manifest and recovered tree remain unchanged.
