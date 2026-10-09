# Recording navigation on desktop and iPhone

Build 1054 captures audible audio on the physical iPhone with Device Hub screen
sharing off. The owner then could not find Close recording or return to the
saved clip. Physical inspection showed disabled workspace navigation and the
account toolbar taking nearly half the screen above the recording panel.

Give the existing recording panel the full workspace while it is open. Hide
the unavailable sidebar and account toolbar, retain their mounted state, and
use a bordered, 48-pixel Close recording button. Keep the recording header in
view while scrolling. Opening focuses the recording heading; closing restores
Home and focuses its saved recording list, now above the private-note form.

Microphone ownership, explicit consent, confirmed stop before close, account
fences, encrypted recordings, retained notebook requests and network policy
remain unchanged. No device recording is erased. A failed or unconfirmed stop
still keeps the panel open. This change does not implement transcription or
activate a service receiver.

Validation uses the existing recording, Home and workspace tests, TypeScript,
and the real signed API/PostgreSQL plus DOM Scribe journey through close,
immediate Home recovery, process remount and identical WAV reopening. The
existing lab still tried to fill a removed participant-location field; its
expectation now follows the current approved consent UI. A meter test waits
for the meter DOM update before asserting its initial value.

Phone-width visual inspection uses actual components with invented saved
state and no microphone or network calls. A fresh iPhone package and physical
retained-clip navigation acceptance remain necessary before declaring this
usability issue resolved. Device Hub must be off during microphone tests.
