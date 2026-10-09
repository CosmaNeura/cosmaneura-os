# Finish a saved recording after notebook mapping

The physical iPhone can map and open a private notebook, but saving the clip's
details leaves its completion unconfirmed. Staging route counts show successful
attach, rejected finish (422), and successful recording read. The earlier
combined POST counts did not distinguish attach from finish.

The device's existing manifest update timestamp advances when a saved recording
is mapped to a notebook. The server incorrectly bounds elapsed wall time between
capture consent and that later update to two hours. An eight-second recording
mapped hours later is therefore rejected even though its PCM is retained.

Use captured frames for the existing two-hour audio limit. Keep completion after
start, enough elapsed time for those frames, and the existing future-time bound.
Preserve the original exact completion request, immutable receipt, owner fencing,
and local audio custody. No wire, schema, device-storage or Scribe admission change.

The signed app stays at 1057. This server change allows a previously rejected
finish to be retried under its original key after the user checks its saved result.
Actual phone acceptance and Scribe transcription remain separate unfinished work.
