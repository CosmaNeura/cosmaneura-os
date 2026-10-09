# Recover a saved recording's existing notebook

A reopened recording with a retained workspace mapping cannot use the unlinked
notebook chooser. If its initial notebook read fails, the recording panel shows
an unconfirmed status but offers no way to read that same notebook again.

Add a visible retry for that read. It opens only the workspace already mapped
in the current owner's encrypted recording, checks the returned identity and
workspace, and discards late results after access changes. It neither changes
the recording's mapping nor creates a notebook or repeats an uncertain write.
Existing metadata save/check/retry controls become available after recovery.

Validate failed read, repeat failure, successful read, same PCM playback and
mapping, and access loss while the retry is in flight. The physical 1056 failure
is still unlocalized because phone control is unavailable; this fixes a
confirmed source recovery gap without claiming it explains that observation.
