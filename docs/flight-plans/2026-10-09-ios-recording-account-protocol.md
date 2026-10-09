# iPhone recording-access protocol fix

Tier 2: native private Scribe recording readiness.

On installed1050, Home and consent render but private recording preparation
repeatedly fails. Its native GET to `/provider-team/identity` sends team and
draft recovery headers, but omitted `X-Cosmas-Workspace-Protocol: 1`. The staging
outer boundary rejects that request with426 before authentication. Read-only
unauthenticated staging probes confirmed426 without the header and401 at the
identity authentication boundary with it; these probes sent no token or audio.

The native request builder now applies protocol1 to both its identity GET and
existing capture POSTs. No origin, token, scope, consent, timeout, storage,
server gate or clinical admission changes. Test the actual compiled Swift
request through both the outer protocol middleware and identity route; omission
of each required header must refuse before authentication. The new test fails
on the original source and passes only with the transport correction.

Validate the complete native-source transport suite, provider identity boundary
suite, native auth/gate tests and a fresh iPhone native binary. Record the exact
tested/reviewed commit in the PR; standing owner local checks and implementer
review govern merge. Merge is separate from hardware delivery and acceptance.
The existing1052 candidate reuses oldnativebytes and cannot fix this defect.

Recovery: restore prior source and rebuild; do not reset or uninstall device
storage. Actual iPhone consent/start/stop/playback and5–7second timing remain
pending. No patient data, upload or transcription is authorized by this fix.
