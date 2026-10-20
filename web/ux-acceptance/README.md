# CosmaBot desktop UX acceptance preview

From `web/`, run `pnpm ux:acceptance` and open `http://127.0.0.1:5196/`.
Use `pnpm ux:acceptance:build` to build the isolated preview.

This renders the actual workspace, notebook, review, settings and recording
components. Notebook and review services return explicitly scripted synthetic
results. Private recording uses generated PCM through the actual encrypted
recording controller and storage; the physical microphone is never opened.
Unsupported account and service operations fail rather than simulate success.
The fixture keeps its scripted saved notebook state in this tab. Working drafts
use the production AES-GCM browser draft store and simulated audio uses the
production encrypted recording store. Both survive reload on this browser
origin. Each tab receives an independent synthetic account scope; another tab
does not represent the same account or shared server. Enter invented information only. This preview is separate from the
normal application build and has no hosted credentials or deployment settings.

The repository tests provide signed UI-to-server, recovery, authorization and
capture evidence. This preview is for layout and interaction acceptance; it does
not establish live service reliability, clinical/model quality or native device
acceptance. See `docs/ux/2026-10-16-implementation.md` for the implementation and
validation record.

## Actual-browser journeys

Start this preview, install the locked `lab/browser` dependencies, then run
`pnpm --dir lab/browser test:workspace` from the repository root. The driver
uses a fresh browser context for each journey and permits network requests only
to the preview origin. `LAB_WORKSPACE_URL` can select an owned loopback port;
`LAB_WORKSPACE_OUTPUT` selects a directory for JSON evidence and screenshots.
`LAB_WORKSPACE_SCREENSHOT_LIMIT` sets the per-run cap from zero to six.

The journeys cover notebook/save/review/reopen, explicit sharing of the exact
saved note with Chief, separate Follow-up and Research drafts, full saved draft
review, scripted public research, encrypted draft reload recovery, another tab's
account isolation, a committed save with a lost reply and exact retry, and
generated-PCM recording/Pause/Stop/reopen and the same visit recorder in both
Conversation and Workspace. Home, chat, review and saved recording
receive WCAG Axe scans. Layout checks run at desktop, iPhone 12 viewport, 320px
width and a reduced 390px viewport height. Phone entry checks the full bot
identity header below the view strip, the reachable editor and Send control,
and the explicit Chief task disclosure. Reduced height approximates keyboard
space; it does not operate or qualify a physical iOS keyboard.

Three additional native-layout journeys use `?native-chat=1&scenario=delayed-native-reply`
to select an invented native identity and a delayed scripted response. They
verify a contained chat viewport, persistent editor/Send geometry and focus,
new typing retained during the old request, actual encrypted reload of that
next question, older-message scroll anchoring, and available-viewport resize.
Home, Workspace and the same recorder's consent setup remain reachable. This
is a browser simulation of the native presentation, with no installed native
app, physical keyboard or native microphone involved.

`?scenario=unconfirmed-save` deliberately commits the first notebook revision
and withholds its reply. Retry uses the same saved synthetic receipt. This is
an interaction failure fixture, not a production service failure injection.
The browser driver never opens a physical microphone, contacts a public research
provider, sends patient email or proves native iPhone acceptance.

An existing bundled runtime can be selected without changing dependencies with
`PLAYWRIGHT_MODULE_PATH` (Playwright package directory) and `AXE_MODULE_PATH`
(local `axe.min.js` file).
