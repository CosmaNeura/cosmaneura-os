# Encounter quick start

The routine visit flow should take no more than three deliberate actions from
an already arranged encounter: **Record visit → Confirm consent & record**.
For desktop meeting audio, one further action selects the Zoom or Chrome window.
The target is under 30 seconds. Sign-in, practice
connection, initial team review, recording defaults and OS permissions are
one-time setup and are not included in that routine-visit target.

The team overview asks for no per-bot form entries. Existing team review and
permission decisions remain explicit. Personalization exposes name and working
preferences first; job focus, capabilities, restrictions and sources are optional
disclosures. Required custom-bot job fields remain visible.

Scribe opens visit notes, with Ask Scribe and Review note one action away. Saved
sources and follow-up work live under More. The recorder remains mounted through
navigation so notes and recording recovery survive switching views. Preparation
and appointment forms are disclosed on demand; recovery and operation status
remain outside those disclosures.

Only region, language and recording-source defaults are remembered, under the current owner's
opaque recovery scope. Consent, patient data and audio are never preferences.
The source and regions remain visible for confirmation at each encounter. Selecting
meeting audio attests a virtual visit. Consent is a fresh deliberate button action;
Enter in a text field does not attest consent. The fresh button can proceed to
capture once preparation succeeds. Reopening, exact retries, recovered audio,
permission recovery and older preparations keep a separate Start action. A changed
account or team invalidates a pending combined start. Existing exact retries,
draft locks, recording recovery and clinical review remain required.

The native meeting picker reuses Scribe PR203's one-button-per-window layout and
its offscreen geometry tests. It retains CosmaBot's existing permission check,
explicit window selection, cancellation and Chrome application-audio disclosure.
Remembering the source never remembers or automatically selects a window.

Validation uses component tests and the actual shared UI at 390×844 and
1280×900 with invented visits and a simulated recorder. The measured local
earlier three-action rehearsal took about 13 seconds. The current combined entry
is covered by component tests; that earlier timing is not a measurement of this
version. These checks prove the interaction path,
not live device or service latency. Physical-device recording through reviewed
SOAP acceptance remains a separate verification after Scribe stabilizes.
