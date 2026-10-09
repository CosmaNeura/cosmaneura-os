# Recover a saved recording's private notebook link

On the physical 1055 iPhone, audio and Close/Home/reopen work, but Home retains
an unconfirmed notebook creation. A saved clip without a workspace mapping
cannot choose a notebook, and a mapped clip without a metadata ledger cannot
save its recording details. These recovery states leave no useful next step
inside the recording panel.

Add an explicit existing-private-notebook chooser to a stopped saved clip.
Only the current owner's unlinked private notebooks are offered; a fresh read
checks the selection before persisting the existing local manifest mapping.
No notebook is created or uncertain create repeated. Add an explicit save for
a reopened clip with no ledger, using the existing encrypted exact-request
attach/finish controller. Reopening still performs no automatic POST; pending
results retain their original check/retry controls. No audio is uploaded or
transcribed, no patient association is made, and microphone/stop guards remain.

Validate actual encrypted PCM through selection, metadata save, and reopening;
withhold late selection after access changes. Extend the signed API/PostgreSQL
DOM journey with a second generated PCM clip recovered into the existing
notebook. Check phone layout and a fresh native package; physical acceptance
and actual transcription/Core workflow remain separate unfinished checks.
