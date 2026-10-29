# Item 12 — Mac / iPhone delivery + real sign-in (plan only)

**Status:** Plan document only. No app code, packaging, signing, secrets, Azure, Clerk console mutation, or device install without explicit John or Shawn yes.

**Worker:** John’s Mac Studio (`mac-studio`), darwin arm64, repo `CosmaNeura/cosmaneura-os`. Disk must stay ≥10 GB free before any build (`df -h ~`).

## Goal

Produce Part B evidence that CosmaBot signs in and runs on:

1. Mac desktop (CosmaBot.app / desktop client on this Studio)
2. iPhone (simulator first; physical device only if John/Shawn authorize)

using **real invited Beta sign-in** (Clerk), synthetic Invented… data only — never PHI or production clinic accounts.

## Preconditions (John / Shawn must decide)

| Decision | Why it blocks |
|---|---|
| Approve Part B desktop/simulator evidence on this Studio | Handoff forbids real sign-in work without yes |
| Which Clerk instance + invited synthetic tester account | Real sign-in; no secrets in repo or agent logs |
| Whether physical iPhone is in scope vs simulator-only | Device install / profiles |
| Whether to use unsigned local desktop build vs notarized artifact | Signing / distribution |
| Merge order for UX drafts (#210–#214 and #204–#209 after Nov 1) | Evidence should sit on the intended UI baseline |

## Evidence sequence (when authorized)

### A. Environment gate (every run)

1. `uname -a`, `pwd`, `git remote -v`, `df -h ~` — stop if free space < 10 GB.
2. Confirm worker placement approved for the session.
3. `git fetch` + checkout the agreed ref (likely `main` after merges, or a named release tag). Do not invent a merge of open drafts.

### B. Mac desktop Part B

1. Build/package desktop from the agreed ref with existing client scripts only (no new infra).
2. Launch CosmaBot.app on Studio.
3. Sign in with the **approved invited** Beta account (Clerk). Do not paste tokens into git, PRs, Slack, or logs.
4. Open a **synthetic** visit / notebook (Invented… labels only).
5. Capture non-PHI screenshots: signed-in home, one visit open, Settings/footer build SHA if #212 is merged.
6. Record: OS version, app version/build SHA, pass/fail per step, blockers.

### C. iPhone Part B (simulator first)

1. Boot an agreed iOS Simulator (prefer ~360 CSS px / SE-class for item 9 regression).
2. Install the agreed iOS/web client build for that ref.
3. Same sign-in + synthetic visit path as desktop.
4. Check Visits tabs single-line scroll + ≥14px type (item 9) and Forgot password affordance (item 8) if those drafts are on the baseline.
5. Screenshots without PHI; note simulator device + iOS version.

### D. Explicit non-goals until separately approved

- Production Clerk or clinic Orgs
- Azure / Terraform / secret rotation
- Merging or deploying any draft PR
- Touching #204–#209 before Nov 1
- Loosening sign-in, session, or permission checks
- Backend changes for Chief visit context (item 3) beyond what UI can do on the cleared baseline

## Dependency map (UX handoff)

| Item | Draft / state | Needed before Part B? |
|---|---|---|
| 1 Visit grey-out / Retry | #210 (do not touch) | Preferred |
| 2 Workspace fast start | #211 (on hold for Shawn) | Preferred |
| 4 Ask Chief on visit | Blocked: EncounterWorkspace vs #210/#211 | Optional |
| 10 Nav highlight / Close notebook | Blocked: same | Optional |
| 11 Build SHA footer | #212 | Preferred (labels the build under test) |
| 9 Phone tabs / 14px | #213 | Preferred for iPhone evidence |
| 8 Forgot password Clerk-only | #214 | Preferred for sign-in path |
| 7 Yes/No vs Waiting for confirmation | Blocked: only on #204–#209 until Nov 1 | After Nov 1 baseline |
| 3 Chief visit context from visit | Blocked: shell/#204 + #210/#211; stop if backend | After serialize |
| 5 Chat streaming / 6 tasks visibility | Deferred | Out of Part B unless claimed |

## Report template (paste into PR or Slack when authorized)

```text
PART_B_MAC_IPHONE
ref:
mac_os:
disk_free_gi:
desktop_build_sha:
desktop_sign_in: pass|fail
desktop_synthetic_visit: pass|fail
iphone_target: simulator|device|skipped
ios_version:
iphone_sign_in: pass|fail|skipped
iphone_synthetic_visit: pass|fail|skipped
screenshots: (paths, no PHI)
blockers:
```

## Stop conditions

- Free disk < 10 GB
- Any step needs secrets, Azure, or infra mutation
- Real patient / production data appears
- Fix requires backend/auth changes beyond this plan → stop and report to John/Shawn
