# Saved recording navigation

Loading the notebook catalog, selecting a notebook, or retrying a saved notebook
used the same busy state as microphone and local audio work. A slow request
disabled Close recording and Play saved recording for the entire wait.

Notebook reads now have their own busy state. Close and playback remain usable
while those reads are pending. Close invalidates their owner immediately after
the local recorder confirms it is closed; a late read cannot map a notebook,
reveal its details, or navigate away from Home. The existing microphone stop
guard remains in force. Opening an already loaded notebook still serializes
its local mapping/navigation with microphone actions.

Validation exercises held catalog, selection, and mapped-notebook reads against
the actual encrypted recording runtime, including playback and reopening of
the same PCM after Close. No recording upload or transcription is introduced.

The staging API completion fix is already active in release
`stg-saved-recording-completion-20261009-r42`. A short clip mapped hours after
recording no longer fails completion solely because that wall-clock delay
exceeds the maximum audio duration. Saved-audio Scribe import and editable
transcript/draft integration remain the next product increment.
