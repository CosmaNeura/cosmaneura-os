# Getting a CosmaBot note into Atlas

**Status:** Research and design only. Nothing in this note is built.
**Date:** November 9, 2026
**Examples:** Invented. Taylor Morgan is not a real patient.
**Sources read:** GPT-5.6 Sol's full write-up, Claude Opus 5.5's working notes (the run stopped before a write-up), this repository, and Atlas's public help and blog.

## Recommendation

Pilot a **copy strip** on the note the clinician has already reviewed. Default to **one plain-text note**, because Atlas's public charting is one note box, not four SOAP boxes. Add a **floating copy list** in Chrome, Edge, and Firefox so the clinician can leave Atlas in front and still see the next section. On a Mac, iPad, or Safari, use split screen instead of the floating window.

The fallback, and only if the pilot shows the clinic still wants CosmaBot after using Atlas's own AI note, is a **Mac hotkey that copies the next section**. The clinician still presses Paste. The phone can move the highlight. The phone cannot paste into Atlas by itself.

If the clinic is already happy with Atlas's own "Promote to Chart Note," stop. Do not build the hotkey.

## One-page summary

Atlas already does the job this bridge is tempted to sell. Since September 28, 2023, an uploaded visit recording in Atlas can become an AI SOAP note on that patient's chart. The current help page lets the clinician review it, edit it, copy it, or save it as a chart note. On August 24, 2026, Atlas added the same recording flow to Android, after iPhone. On August 26, 2026, Atlas added recording that starts inside the open chart, so the audio never has to be moved from another app. Atlas's own marketing says that extra handoff is how recordings get attached to the wrong chart.

A copy/paste bridge from CosmaBot puts that handoff back. CosmaBot is worth it for an Atlas clinic only when the clinician wants **this reviewed draft** more than Atlas's draft. The honest reasons to test are: they already trust CosmaBot's wording, they want patient instructions or order wording kept out of the chart note, or they want one review habit across clinics that are not all on Atlas. "Atlas has no AI scribe" is not one of those reasons.

Both earlier passes agreed on the right first build: a web page of copy buttons, no install, no Atlas API, and no silent paste from the phone. Sol wrote that up cleanly and added a strong safety list. Opus, in notes that never became a write-up, added the three ideas this recommendation keeps: a floating panel so the clinician stops alt-tabbing, a phone that sends "show section 2" while the signed-in computer loads the text itself, and a warning that a pasted `#` may trip Atlas's macro menu. Opus also noticed the written rule against automating the clinician's screen. Sol's fallback, a browser extension that types into Atlas's fields, runs into that rule.

Build the copy strip in about **6 to 9 engineer-days**. That covers one-note copy, per-section copy, plain text that avoids a leading `#`, a floating panel where the browser allows it, a button that clears the clipboard, and a check that the draft has not changed since the copy. It does not cover a lawyer's review or a clinic security review.

Build the Mac hotkey only after the pilot, in about **8 to 14 engineer-days**, and only for clinics that already use the Mac app. Windows stays on the web page.

The pilot's first hour is a look at a test chart, with invented text. It answers two questions before more software: is Atlas one box or several, and does this clinic still want a second scribe?

## What Atlas already ships

Public Atlas pages, read November 9, 2026:

- [Creating SOAP notes from transcriptions with AI](https://atlas.md/help/view/Creating-SOAP-notes-from-transcriptions-with-AI/) says a doctor–patient recording becomes an AI SOAP note. The clinician opens it, then chooses **Promote to Chart Note**. From there the choices are **Add Note**, **Edit AI Results**, and **Copy to Clipboard**. A second path, from the chart's AI button, offers **Add Note** (a top-level chart note) or **Add to Thread** (kept with the original audio). The saved note stays linked to the audio and the transcript.
- The [September 28, 2023 announcement](https://blog.atlas.md/2023/09/whats-new-in-atlas-md-ai-summaries-and-soap-notes/) is when that AI summary and SOAP feature launched.
- [In-chart audio recordings](https://blog.atlas.md/2026/08/whats-new-in-atlas-md-in-chart-audio-recordings/), August 26, 2026, records from the open chart and sends the result through the same AI summary or SOAP path. Atlas describes the point of it as removing a second device and a manual upload.
- [Voice recording on Android](https://blog.atlas.md/2026/08/whats-new-in-atlas-md-voice-recording-in-atlas-md-mobile-for-android/), August 24, 2026, says iPhone already had this, and Android now records in Atlas's own app, attaches the audio to the chart, and prepares it for an AI SOAP note.
- [How to use the macro autocompleter](https://atlas.md/help/view/how-to-use-macro-autocompleter/) says a chart note starts from the plus button, choosing **note**, and typing in that box. Typing `#` opens a menu. `#AI` can insert ICD-10 suggestions or a differential. Other hashes pull allergies, medications, demographics, a signature, and the patient's name.
- [Ask Atlas](https://atlas.md/features/) and the [AI page](https://atlas.md/ai/) also list transcript summaries, SOAP notes, chart summaries, and diagnosis suggestions as included product features. Pricing lists them in the subscription.

Nobody outside Atlas has confirmed the live screen. The public record still points one way: a chart note is one text box on the patient's timeline. Separate Subjective, Objective, Assessment, and Plan boxes are not described. The AI result is copied or saved as one note.

### What that means for a sale

For a clinic that lives in Atlas, CosmaBot is a second scribe sitting next to a first scribe that already knows the chart.

Atlas's scribe starts on the right chart. CosmaBot's paste ends with a human looking at two windows and hoping they match. That is a worse safety story than Atlas's August 2026 recording feature, unless CosmaBot's draft is the one the clinician wants to keep.

Use the pilot to ask that directly, on a test chart:

1. Do you already press Atlas's AI SOAP button?
2. What do you still fix by hand after Atlas writes the note?
3. Do you need anything Atlas is not writing, such as a patient-instruction blurb or order wording that should stay out of the chart note?
4. Are you keeping CosmaBot because other clinics are not on Atlas?

If the answers are "yes," "almost nothing," "no," and "no," the copy strip is enough to be polite, and the rest of this note is a paper design. If they want CosmaBot's wording, the copy strip is the product, and speed comes second.

## Where the two write-ups agree

Sol finished a recommendation. Opus left working notes and was cut off while checking how this repository treats docs. The agreement is still clear:

- Start with a zero-install web page of copy buttons.
- Offer both "copy this section" and "copy the whole note."
- Keep the clinician as the person who pastes, saves, and signs in Atlas.
- A phone cannot reliably push text onto a desktop clipboard while Atlas is the front window. A web page is not allowed to do that from a background tab.
- Apple Universal Clipboard and Windows Phone Link are a personal-device shortcut, not the product. A consumer clipboard sync can land on every machine on that Apple or Microsoft account, and we cannot expire it.
- Look at the clinic's real editor with invented text before anyone promises to fill fields.
- The `.ics` calendar work in PR 330 does not teach us anything about Atlas's note screen. This repository's Atlas plugin still returns "not supported" for patients and appointments, and the calendar import is a file a person uploads.

Sol's safety rules are the right ones to keep: copy on a click, show the section name, drop the text when the visit closes or the person logs out, keep note text out of logs and addresses, and treat the computer's clipboard as something other apps can read. The product already has a click-to-copy control for answers (`CopyAnswer`) that falls back to "select this text and copy it yourself" when the browser refuses. The note screen already stores sections in order and a hash of that order.

## Where they differ

| Topic | Sol | Opus notes | What this note uses |
| --- | --- | --- | --- |
| First pilot | Transfer View, 3–5 engineer-days | Same page, plus a floating panel. Sizes given as Small / Medium / Large | Copy strip plus floating panel where it works. 6–9 engineer-days |
| Fallback | Browser extension that fills Atlas fields, 8–12 engineer-days | Mac paste queue in the app we already ship, then a phone remote. Extension later, because of install rules and store review | Mac hotkey that copies, then the clinician pastes. Phone only moves the highlight |
| Phone | A paired session that sends the note, encrypted, to a desktop page. Desktop click still copies | Phone sends a pointer. The desktop, already signed in, loads the section itself | Opus's pointer. No second copy of the note in transit |
| Atlas's own AI | Used to ask whether the editor is one box or four | Called the audio path a competitive risk, then set it aside | It is the reason the pilot can end early |
| Sizes | Engineer-days, as the brief asked | Refused engineer-days because of a conflicting instruction, and said so | Engineer-days, as this brief asked |

## What Sol got wrong or left out

Sol's layout warning is the right instinct, and the safety section is the best writing in either pass. These parts do not hold:

- **Add Note and Add to Thread are different.** Sol said both create a top-level chart note. The current help page says **Add Note** is the top-level chart note and **Add to Thread** stays attached to the audio. The same page now leads with **Promote to Chart Note** and **Copy to Clipboard**. Sol's paraphrase matches an older, shorter reading of that page.
- **Atlas's own scribe is the main fact, and it is underweighted.** The write-up treats Atlas's AI page as evidence about fields. It misses in-chart recording (August 26, 2026) and Android recording (August 24, 2026). Those features are the competing workflow, and they remove the wrong-chart step that copy/paste puts back.
- **Four boxes and one box are not equally likely.** Public help describes one note you type into, one AI result, and one clipboard copy. The pilot should still look, and the software should survive either shape. The default output should be one labeled note.
- **The recommended fallback fights a written rule.** `AGENTS.md` says not to add browser automation. The Atlas connector note says not to automate the clinician's screen. An extension that writes into Atlas's boxes is that kind of automation, even with a confirm click. A copy list inside an extension is only a harder-to-install version of the web page. Filling fields needs an explicit owner exception before anyone builds it.
- **The phone design ships the note twice.** The desktop is already signed into the same clinic and the same person. It can load the saved draft. Sending the note text through a relay, even encrypted, is extra storage, extra expiry rules, and extra ways to deliver the same draft twice.
- **The build size is tight for the safety list attached to it.** A row of copy buttons on the current note screen is a few days. Sol also specified idle expiry, a bound revision, content-free metrics, and tests for every failure. That is the 6-to-9-day pilot below, not a 3-to-5-day one.
- **Operating-system clipboard sync is a warning, not a fifth product.** Calling it 2–4 engineer-days of "qualification" makes a policy memo look like a build.
- **No `#` warning, no iPad, no floating panel.** Those are the practical holes. Atlas notes open a menu on `#`. Many direct-care clinicians chart on an iPad, where a desktop helper never runs. A floating panel is what removes the alt-tab, and Safari still does not offer it.

Sol was right that a phone tap must not be sold as a silent paste, that Chrome and Edge are the only sane first target for any extension, and that a Windows helper is a new product.

## What Opus got right, and what the notes never finished

The notes are not a decision. They stop while looking for doc checks. Taken as ideas, they are the better product pass on three points:

- **Floating panel.** Chrome, Edge, and Firefox 151 and later can pop a small always-on-top page ([Can I use: Document Picture-in-Picture](https://caniuse.com/mdn-api_documentpictureinpicture), [CSS-Tricks on Firefox 151](https://css-tricks.com/creating-web-widgets-using-the-document-picture-in-picture-api/)). Safari, including iPad, cannot. The panel still needs a click to copy. A message from the phone is not a click.
- **Phone as a remote, not a pipe.** "Show section 2 of this saved draft" is the whole message. The computer fetches the words. That matches how this repository already works: a saved encounter can reopen on another signed-in device, and an active recording cannot jump from the phone to the Mac (`docs/COSMABOT_ARCHITECTURE.md`).
- **The `#` macro, flagged as unproven.** Typing `#` in an Atlas note opens the macro menu. Whether a paste does the same is untested. The notes were right to leave it as a test, not a fact.
- **The automation rule.** The notes caught it before recommending a field-filling extension.

The notes also left real gaps:

- They set Atlas's scribe aside as "not directly our concern." It is the concern.
- They wondered whether pasting a transcript into Atlas would make Atlas write the SOAP note. The help page does not say that. It describes audio in, and an AI button on the chart. Feeding Atlas's AI our transcript would also throw away the reviewed CosmaBot draft. Leave it as a question for the test chart, not a design.
- They ranked a Mac paste queue as the fallback without knowing whether the clinic is on Mac. The fallback below is conditional on that.
- They never wrote the clinician steps, the safety rules, or the stop condition.
- They declined engineer-days. This brief asked for them, so this note gives them. The ranges are build size for one engineer who already knows this repository. They are not a promise about a calendar week, and they leave out legal review, a clinic's IT queue, and a signed-app release.

## Weak assumptions

1. **That an Atlas clinic wants a second scribe.** Weakest assumption in both passes. The pilot has to be allowed to end with "use Atlas."
2. **That the note screen has four boxes.** Sol designed as if that were a coin flip. Public docs describe one box. A clinic template could still surprise us, which is why the test chart comes first and the software supports both.
3. **That a paste of `#` fires a macro.** Plausible, unproven. The copy text should avoid a leading `#` anyway, and the test chart should include one hash, a bullet, a blank line, and an apostrophe. Invented sample: "Taylor Morgan reports an invented sore throat for two days. No # code was discussed."
4. **That the clinic's computer can run an extension or a helper.** Unknown by design. The first build assumes it cannot.
5. **That "the phone" means a remote control for a desktop.** It may mean the chart is on an iPad. Split screen is then the whole workflow.
6. **That Sol's 15-minute transfer session is a separate object.** The reviewed draft is already behind login. A second session that holds the same words is extra. Expiry can be "this view closes when the note changes, the person logs out, or they press Done."

## The pilot: copy strip

### What the clinician does

1. Finish the review in CosmaBot and save the draft. An in-progress recording stays on the phone that started it. This path starts after the draft exists.
2. Open **Copy for Atlas** on that draft. The screen shows the section names in the draft's order, the time of this version, and two main buttons: **Copy full note** and **Copy this section**. Patient instructions and order wording, if we have them, are separate buttons and are left out of the full note.
3. On the Atlas computer, open the test chart or the real chart and look at the name.
4. If the chart note is one box, click **Copy full note** and paste. The text looks like this:

```text
Subjective
Taylor Morgan reports an invented sore throat for two days.

Objective
No exam was recorded in this invented example.

Assessment
Invented viral sore throat.

Plan
Fluids, rest, and a follow-up if swallowing worsens. Clinician to review before saving.
```

5. If the chart has separate boxes, click the section, paste, and go to the next highlighted section. In Chrome, Edge, or Firefox, **Pop out** keeps that list above Atlas. On Safari or an iPad, split the screen. The pop-out is the same page, not a new product.
6. Read it in Atlas. Save or sign with Atlas's own buttons.
7. Press **Clear clipboard**, which copies a single space over what we just copied, then **Done**.

The full note uses words for labels. It does not use a markdown heading, because a line that starts with `#` is how Atlas opens its macro menu.

### Phone and iPad

- **Charting on an iPad.** Open CosmaBot in one half of the screen and Atlas in the other. Copy and paste there. No pairing step.
- **Charting on a computer, phone in hand.** The phone shows the same section list for a saved draft. Tapping **Next** tells the signed-in computer which section to highlight. The computer loads the words. The tap does not copy and does not paste. The person at the computer still clicks **Copy** or uses the Mac hotkey in the fallback.
- **Phone and computer are different logins, or the computer is locked.** The phone shows the copy buttons for use on that phone. We do not send the note text to a machine that is not signed in as this clinician.

### Install, Mac, Windows

No install. The page is the CosmaBot web app they already use. Mac and Windows behave the same. Paste is Command-V or Control-V. The floating panel is missing in Safari, so a Mac that only uses Safari gets split screen, which is the same gesture as the iPad.

### Safety

- The clinician reviews in CosmaBot and again in Atlas. Nothing saves or signs itself.
- The copy is plain text of the selected section or the labeled note. It does not include the recording, the transcript, or a chart identifier.
- If the draft changes after this screen opens, the buttons stop until the clinician reopens the new version. Editing invalidates the earlier copy, same rule as the rest of the product.
- Logs may record that a copy was attempted and whether the browser allowed it. They do not record the text, the Atlas address, or the page title. This repository already scrubs clinical note fields from connector logs.
- The clipboard is the leftover risk. Other programs, clipboard history, and a shared exam-room login can keep the text. The clear button and **Done** are the product side of that. The clinic still decides whether clipboard history is on.
- A locked or shared computer should be signed out of CosmaBot when the clinician leaves. The copy screen does not survive that.

### What fails, and what the clinician does

- The browser blocks clipboard access. The section stays on screen with a normal select-and-copy.
- The paste loses bullets or line breaks. The default is plain text. The test chart is where we see it.
- A `#` opens an Atlas menu. The clinician presses Escape, and we treat that pattern as something the copy text must avoid.
- The wrong chart is open. We cannot see Atlas. The clinician checks the name before pasting.
- The floating panel is unavailable. The same buttons are on the main page and in split screen.
- The draft was edited on the phone after the computer opened it. The computer refuses the old highlight and reloads.

### Later, if Atlas gives an API

The same reviewed draft, the same section order, and the same hash become the payload of a real write. The clinician still sees the destination chart and presses a confirm. The API call uses that exact version once. A retry checks whether the first try landed. It does not invent a second note, and it does not sign.

## The fallback: Mac hotkey

Build this only after the pilot, and only when all of these are true:

- The clinic wants CosmaBot's draft often enough to care about seconds.
- They chart on a Mac that already runs CosmaBot, on a personal login rather than a locked shared PC.
- The test chart showed that one-paste is awkward, usually because there really are separate boxes.

### What the clinician does

1. Open the same reviewed draft. The Mac app shows a small line: "Next: Objective. 2 of 4."
2. Click in the Atlas box.
3. Press the hotkey. The Mac copies Objective to the clipboard and moves the line to Assessment. It does not press Paste.
4. Press Command-V.
5. If the phone is being used as the remote, **Next** on the phone only changes which section the hotkey will copy.
6. Quit the transfer, or lock the Mac. The queue is dropped. A crash drops it too. The clinician starts again from the saved draft.

### Why this shape

A global hotkey is the piece a web page cannot do while Atlas is in front. Copying to the clipboard, and letting the clinician paste, stays on the safe side of "do not automate the clinician's screen." Typing the paste for them needs the Mac Accessibility permission and is the automation we are not building.

Windows does not get this fallback. A Windows helper would be a new signed app, a new update story, and a fight with clinic security software. Those clinics keep the web page.

### Size and risk

About **8 to 14 engineer-days** for the hotkey, the on-screen "next section" line, the phone highlight message, and tests that a lost focus or a changed draft does not paste the wrong section. Shipping it to a clinic also needs a signed Mac build and a fresh release check. The current Mac helper package path does not itself sign or ship. That release work sits outside the 8 to 14 days.

The main risks are a hotkey that collides with one the clinician already uses, a shared Mac that still has the note in clipboard history, and building this for a clinic that quietly goes back to Atlas's own SOAP button.

## Ideas that wait

- **An extension that fills Atlas fields.** It needs a stable Atlas screen, a clinic that allows extensions, and an owner exception to the automation rule. If the screen changes, it must stop and show the copy buttons. It is a later project, not the fallback.
- **A Windows helper, and any helper that pastes by sending keystrokes.** Highest install cost, and it is the automation path.
- **A relay that carries the note from the phone to the computer.** The signed-in computer can read the draft. A relay is a second store.
- **Universal Clipboard or Phone Link as a required step.** Fine as a personal habit the clinic has already accepted. Bad as something we tell every clinic to turn on. Microsoft's cross-device copy page lists specific Android phones, and the page is written for Android and a PC. An iPhone is the device CosmaBot already ships, so Phone Link does not cover the pair a clinic is most likely to have ([Microsoft](https://support.microsoft.com/en-us/windows/apps/phonelink/seamlessly-transfer-content-between-your-devices)).
- **Asking Atlas's AI to rewrite a pasted transcript.** Unproven, and it discards the draft the clinician just reviewed.

## Pilot visit, before or during the first week of the copy strip

Do this on a test chart or an empty note. Do not record a real chart, do not take a screenshot of one, and do not copy a real note into a ticket.

1. Which browser, and is the computer a Mac, a Windows PC, or an iPad? Personal laptop or shared exam-room machine? Can they install anything?
2. Is a new chart note one box or several? What are the labels?
3. Paste the invented sore-throat note, including a hash, a bullet, a blank line, and an apostrophe. Write down whether a macro menu opens and whether the line breaks survive. Throw that test note away.
4. Ask the four sales questions in the section above.
5. Time a willing clinician from "draft is ready" to "I would save this in Atlas," using only the copy strip. Count mis-pastes. Do not collect the text.

Continue to the Mac hotkey only if they are still choosing CosmaBot's draft and the one-paste path is actually slowing them down.

## Rough sizes

| Work | Engineer-days | Starts when |
| --- | --- | --- |
| Copy strip, floating panel, clear-clipboard, revision check | 6–9 | Now, if a pilot clinic is real |
| Test-chart visit | A clinic session, not a build | Before promising field-by-field paste |
| Mac hotkey and phone highlight | 8–14, plus a signed Mac release | After the pilot says the clinic still wants CosmaBot |
| Extension that fills fields | Leave unestimated | After an owner exception and a stable picture of Atlas's screen |

The 6 to 9 days assume the current reviewed draft can already be opened in the web app, and that we add the copy screen there rather than inventing a new note model.

## Sources

- [Atlas help: Creating SOAP notes from transcriptions with AI](https://atlas.md/help/view/Creating-SOAP-notes-from-transcriptions-with-AI/)
- [Atlas blog, September 28, 2023: AI summaries and SOAP notes](https://blog.atlas.md/2023/09/whats-new-in-atlas-md-ai-summaries-and-soap-notes/)
- [Atlas blog, August 26, 2026: in-chart audio recordings](https://blog.atlas.md/2026/08/whats-new-in-atlas-md-in-chart-audio-recordings/)
- [Atlas blog, August 24, 2026: voice recording on Android](https://blog.atlas.md/2026/08/whats-new-in-atlas-md-voice-recording-in-atlas-md-mobile-for-android/)
- [Atlas help: macro autocompleter](https://atlas.md/help/view/how-to-use-macro-autocompleter/)
- [Atlas help: AI macros](https://atlas.md/help/view/ai-macros/)
- [Atlas features](https://atlas.md/features/)
- [Atlas AI overview](https://atlas.md/ai/)
- [Can I use: Document Picture-in-Picture](https://caniuse.com/mdn-api_documentpictureinpicture)
- [CSS-Tricks: Document Picture-in-Picture, including Firefox 151 and the Safari gap](https://css-tricks.com/creating-web-widgets-using-the-document-picture-in-picture-api/)
- [Microsoft: cross-device copy and paste](https://support.microsoft.com/en-us/windows/apps/phonelink/seamlessly-transfer-content-between-your-devices)
- This repository: `docs/COSMABOT_ARCHITECTURE.md`, `docs/plugins/atlas-md.md`, `docs/beta/EHR_CONNECTOR_WORKSTREAM_20261025.md`, `AGENTS.md`
