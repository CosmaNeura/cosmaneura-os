# CosmaBot iPhone UI: first implementation batch

Implemented October 22, 2026 against `7f30834` on local branch
`fix/iphone-ui-handoff-20261022`. The owner requested implementation, chose the
responsive layout with persistent bottom tabs, and chose to hide pages that
cannot render while disconnected. Work and validation stayed in this conversation
and used synthetic data only.

The completed checkout is saved outside Desktop and iCloud at
`~/Cosmas-Work/cosmabot-iphone-ui-20261022`. The original handoff archive is
preserved at `~/Cosmas-Handoffs/2026-10-22/cosmabot-ui-handoff.zip`.
The Desktop checkout and its missing Git index were not changed.

## Implemented behavior

- Phone navigation stays at the bottom in one row. Its measured height reserves
  space below page content, including the bottom safe area. The compact header
  cannot scroll independently; top-level navigation resets document and header
  scrolling. Account controls remain reachable. The existing authenticated native
  Home/More layout is retained.
- Without an identity, the start screen exposes only Visits and notes. A connected
  synthetic workspace also exposes Practice work and Settings; Home remains hidden
  because it requires an authenticated identity. Settings has an active tab and its
  existing Done control. A defensive disconnected Settings route also has Done.
- Network failures name the unreachable workspace service and offer Dismiss. Safe
  failed reads offer Try again. Opening a synthetic encounter can seed data, so its
  general retry checks `GET /health` instead of repeating that write; after the service
  recovers, the screen asks the user to open an encounter. Existing exact-request
  write retries, retained drafts and conflict/recovery notices remain intact.
- Fixed Canvas overlays no longer paint white strips above dialogs. Sample and
  workspace dialogs respect safe-area insets. The sample header and footer remain
  outside its scrolling content, and its close button measures at least 44 by 44
  CSS pixels at the tested phone size. Jumping to handoffs leaves their heading
  below the header. Completion appears only after follow-up review; editing the
  message invalidates that review.
- Execution proof requires explicit `VITE_SHOW_EXECUTION_PROOF=true` and is hidden
  in the phone layout. Its legacy screen styling and wording are still pending.

## Validation

| Check | Result | Evidence |
| --- | --- | --- |
| Full web suite | 296 files passed, 17 skipped; 4,232 tests passed, 103 skipped | [web-full.log](validation/2026-10-22-iphone/web-full.log) |
| Synthetic web build, including TypeScript | Passed; existing large entry chunk warning remains (1.56 MB before gzip) | [web-synthetic-build.log](validation/2026-10-22-iphone/web-synthetic-build.log) |
| Composed iOS simulator build | `BUILD SUCCEEDED` | [ios-simulator-build.log](validation/2026-10-22-iphone/ios-simulator-build.log) |
| Final isolated simulator install and launch | Succeeded on the existing synthetic iPhone 12, iOS 26.5; bundle `com.cosmasos.synthetic.w90u` | [Simulator start](screenshots/2026-10-22-iphone/iphone-simulator-final.png) |
| Real local backend, stopped and restarted | Unreachable error, safe health retry, then explicit open succeeded without relaunch | [Offline screen](screenshots/2026-10-22-iphone/phone-offline.jpg) |
| Phone Settings at 390 × 844 | Done visible; three 64 px tabs at y=780; Settings current; no horizontal overflow; both scroll offsets 0; header overflow visible | [Final Settings](screenshots/2026-10-22-iphone/phone-settings-final.jpg) |
| Sample review at 390 × 844 | Close target 44 × 44.67 px; handoff jump visible; completion gated by checkbox | [Reviewed sample](screenshots/2026-10-22-iphone/phone-sample-complete.jpg) |
| Native sample click-through after unlocking the Mac | Sample opened by tap; content swipe kept header/footer visible; note checkbox enabled handoffs; jump placed heading below header; header close returned to workspace | [Native handoffs](screenshots/2026-10-22-iphone/iphone-sample-handoffs-native.png), [Dismissed](screenshots/2026-10-22-iphone/iphone-sample-dismissed-native.png) |

Tests cover hidden pages, active Settings and Done, phone scroll reset, account
controls, developer flag gating, network classification, safe read retries and
retained write recovery after dismissing an error. The shared Settings test helper
now waits for availability reads to enable a visible connection card before clicking
it. The full suite was run with the local API paused to keep unit fixtures isolated;
its existing signed integration lab skips are retained, not counted as passes.

The backend used a fresh loopback-only Postgres database and the local synthetic
FastAPI service. No real vendors or production services were connected. The pinned
Scribe source was read-only; composition output was separate. Temporary validation
servers were stopped after evidence was saved. The saved command logs have trailing
whitespace normalized; their diagnostic content and outcomes are unchanged.

Rerun from `web/`:

```sh
corepack pnpm exec vitest run --maxWorkers=2 --minWorkers=1
VITE_WORKSPACE_ENABLED=true VITE_COSMAS_ENV=synth_os corepack pnpm build
```

Compose and build the Apple shell using the original handoff's R section and
`scripts/prepare-apple-synthetic.py`, with output in a new directory.

## Remaining handoff work

- Verify actual VoiceOver access and implement/test native Dynamic Type. Native
  sample taps and swiping passed after the owner unlocked the Mac. Device Hub's
  automation tree still omitted the embedded web controls; that observation does
  not establish whether VoiceOver can read or activate them.
- Measure cold and warm starts on a physical iPhone before performance changes.
  No launch-time improvement is claimed.
- Confirm which original scroll container hid the old header. The revised layout
  removes independent header scrolling and keeps navigation visible; it does not
  establish the original cause.
- Resolve the remaining product wording, theme, landing and avatar decisions from
  the handoff, and revisit the opt-in execution-proof screen's style and copy.

This is the first batch of improvements; the full handoff remains open. The
October 22 checkpoint was local. The owner requested GitHub publication on
October 23. Publishing this source branch does not update the physical iPhone;
that requires a subsequent signed device build and installation.
