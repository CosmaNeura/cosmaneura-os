# Native recording UI and upload connection — September 27, 2026

Fresh configured iPhone encounters now select the retained native recorder from PR30.
Opening or remounting attaches controls without starting or stopping audio. Start,
Pause, resume preparation and Stop/upload use its metadata-only bridge. The native
process retains PCM, encryption keys, lease/reservation renewal and source custody.

The durable `owned:native` session marker rejects old/browser/desktop writers.
Existing legacy/configured recordings remain on their original controller and
ciphertext namespace. Selection also checks unclaimed legacy queues before
creating a native owner marker; an attachment failure keeps that marker.

The uploader reads only
`cosmas-provider-queue:v1:<native-account-recovery>:<workspace>:<session>:`.
It reuses the existing ciphertext upload/receipt transport. After native sealing,
it confirms native host closure before uploading/completing, preserving the
sealed journal and frozen completion key/lease. This ordering permits completed
visits to reopen through creator review without stranding a retained native
owner. Completion requires every recorded position to have a registration
receipt; ciphertext purge retains the receipt metadata.

The UI supports cancelling a pending native Start, explicit input selection and
separate preparation/Start for resuming. Native limits remain 360 admitted
positions; the library's larger storage capacity is not permission for longer
recording. The new native path follows the pinned native lease/reservation
service; it does not migrate or replay the older renderer-owned profile journal.

Validation targets: native metadata/identity fencing, detach/remount, pause and
start cancellation, actual ciphertext transport/registration/completion, lost
completion response, namespace separation, retained backend selection, existing
encounter navigation and transcript-to-SOAP review. Upstream provenance is in
`tests/native/recording-ui/UPSTREAM.json`.

This source connection is not physical-device or live-service acceptance. A
matching installed build, deployed OS native context endpoint, authorized Core
integration, fresh native sign-in, background/interruption recording and actual
recording-to-reviewed-SOAP still require acceptance. No Scribe checkout, live
recording, staging state or distribution certificate is changed by this source
work.
