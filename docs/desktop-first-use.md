# Desktop first use

Home is the signed-in entry screen. Practice work, team settings and Connections
open independently of an appointment. The existing five-bot provider preset is
shown before the first note; its normal capability review and user-confirmed save
remain in force. Account connections are optional after the first useful note.

A reserved solo owner chooses **Set up my practice** and confirms practice name,
name and optional specialty. An existing owner completes the same confirmation.
Members use **Join an existing practice** and retain owner approval. The HTTP
request cannot provide an owner flag, organization or identity. For a new,
dedicated beta practice, a reviewed host bootstrap manifest may be passed to
`bootstrap-beta-identity --reserve-first-owner --manifest <protected-file>`.
This host-only action reserves the exact verified issuer, organization and
subject for seven days; runtime credentials cannot insert or rewrite it. It
cannot claim an existing practice. Completing setup retains an immutable receipt.

**Scribe** on Home opens private recording consent immediately. Account authority,
encrypted storage and the native microphone permit prepare in parallel. After
explicit consent, real microphone capture starts independently of notebook API
creation. Title and patient selection are optional at this point. Stop saves audio
encrypted on this device; playback and reopen verify the saved PCM. The interface
labels it as not synced and not transcribed. A notebook or metadata receipt does
not make the audio available on another device. Each recording interval is bounded
to fifteen minutes; a pause or interruption requires fresh consent to resume.

The target is five to seven seconds from completed authenticated sign-in to
selecting Scribe and starting capture. Functional API and simulated hardware
checks do not establish that target on a physical iPhone or Mac. First-time OS
permission prompts and the user's consent response must be recorded separately.

**Start a private note** creates an owner-scoped notebook through the actual
workspace API with no patient or appointment. Notebook revisions, private bot
source review and private team draft handoffs reuse the existing paths. An
unlinked note exposes no patient-bound capture, public Research, selected external
sources or external connector action tools. **Link a confirmed visit** requires
explicit patient/appointment confirmation, a current draft revision and an
immutable link receipt. It keeps the note's origin and history. There is no
upstream chart write from linking.

Unknown creation or linking outcomes are retained as exact requests in encrypted
recovery storage. A read-only resolve can recover the saved result. If no result
is found, only a user-requested retry of the same idempotency key is offered; a
late original request cannot produce a second note or link.

The additive connection catalog v2 describes supported actions, runtime setup,
installed accounts and user authority separately. It preserves exact v1 clients.
Coming-soon services and unavailable hosted booking/collection actions cannot
start a connection flow. Implemented practice-managed services explain setup;
Google/Microsoft offer the supported account sign-in paths. Account connection,
read verification, accepted request, delivery and recipient acknowledgment keep
separate meanings. Saved-work recovery remains accessible under current access.
The product can guide supported setup; it cannot build, install, deploy or
provision a missing connector inside chat.

Release service and desktop together after the normal migration/release gates.
The required schema head is `f96b1c4d2357`; the client requires `practice_setup:1`
and `private_draft:1`. A clean committed source and its tree are bound into the
packaged desktop provenance. Updating the package alone cannot update the service.

The broader 120-second first-use setup target remains unmeasured with human practitioners.
Observe at least ten first-time solo-practitioner sessions from verified sign-in
to editable private note; record p95 time, completion rate, support requests and
connector dead ends. Automated API/DOM journeys qualify functionality and failure
recovery; they do not establish human usability or physical-device acceptance.
