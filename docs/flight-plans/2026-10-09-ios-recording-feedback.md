# iPhone permission startup and recording feedback

Tier 2: private Scribe microphone and local playback. Build1053 fixed recording
readiness on the owner's iPhone12. First Start displayed microphone permission,
then Paused. Resume provided no immediate visible activity. The device retained
8 seconds in one chunk, but the owner reported silent playback. This is failed
hardware acceptance; a saved duration alone does not prove usable audio.

Private Start now returns its owned Core session before microphone permission
awaits, so Stop can cancel that exact pending owner. The Core permission adapter
waits at most1.5seconds for the OS dialog to restore foreground activity. Stop,
denied permission, account changes and real background transitions still fence
startup; there is no automatic resume or source fallback.
Private in-person capture uses the existing measurement-input setup without
voice-chat processing or a playback graph. Its lifecycle remains foreground-only;
backgrounding still terminates input. The foreground PCM composition uses this measurement profile; native encrypted
recording keeps its separate existing profile.

Recording shows an immediate live timer, saved duration separately, and the
existing content-free iPhone signal presentation. Its read-only native method
returns levels, bounded route codes and mute state only for the current private
owner. Late or missing replies cannot preserve a live meter after Stop. No
samples, identity or device names enter this response or any network request.
Interruption reasons explain Paused, and consent remains required for Resume.
Verified playback warns when every PCM payload byte is zero, excluding WAV
headers. It retains the original encrypted recording and never changes it.

Validate permission dismissal/cancellation, actual bridge resampling/signal,
runtime zero/nonzero WAV checks, panel Stop/late replies, TypeScript and fresh
arm64 native compilation. Review and record the exact commit and results in the
PR under the owner's standing local-checks merge policy. Device delivery and
audible capture/reopen/playback remain separate acceptance requirements.

Recovery: rebuild the previous source and update in place. Preserve1053 and all
device storage; do not uninstall, reset permission or delete recordings. Notebook
metadata remains unconfirmed against the older staging schema. This change
requests no transcription, upload, clinical admission or production activation.
