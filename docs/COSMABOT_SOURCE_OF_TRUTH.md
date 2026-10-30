# CosmaBot source and release index — October 30, 2026

Open one repository: `CosmaNeura/cosmaneura-os`. For this consolidation, use
branch `recovery/cosmabot-source-of-truth-20261030`; after review and merge,
use `main`. On John's Mac the matching independent clone is
`/Users/jw/Desktop/Cosmas/CosmaBot-Workspace`. Its Git objects do not depend on
any `/private/tmp` worktree. Do not open an expanded handoff as the development
workspace or reset another checkout to match this one.

## Source ownership

| Work | Source to develop | State |
| --- | --- | --- |
| Chief-first Messages and mobile layout | `web/src/MessagesPresentation.tsx`, `messages-presentation.css`, `WorkspaceShell.tsx` | Integrated in GitHub main; October 23 accepted plan in `docs/ux/2026-10-23-chief-first-messages.md` |
| Practice, settings, logout and connector chooser | `web/src/PracticeHome.tsx`, `SettingsHub.tsx`, `settings-hub.css` | Integrated baseline; later local UI changes preserved separately below |
| EHRs and task flows | `web/src/EhrReadProviders.tsx`, `EhrReadTask.tsx`; `src/cosmas_os/adapters`, `application`, `ports` | Atlas.MD, Elation, Tebra and Athena implementations are discoverable here; source presence does not establish live vendor acceptance |
| Email, calendar, research and fax UX | Google/Microsoft/calendar/research/fax panels under `web/src`; corresponding backend application/adapters | Integrated source; live connections and operational acceptance require their own evidence |
| Independent Cosmas MD practice/identity | `src/cosmas_os/standalone_runtime.py`, `application/standalone_practice.py`, `clients/shared/standalone-feature-profile.mjs` | Separate CosmaBot identity/storage; no Core deployment required |
| Mac shell and shared native implementations | `clients/desktop`, `clients/apple`, `clients/capture` | Authoritative implementation owners |
| Recovered iPhone project and composed dependencies | `apps/capture` | Released 1107 baseline, configuration replaced with an unconfigured template; see its README/provenance |
| Additional local provider/connector UI edits | `docs/recovery/20261030` | Preserved, unreviewed; not applied to runtime source, tested or released |

`apps/capture` retains the already-composed release closure so its missing app,
package wiring and SDK source cannot disappear again. Shared implementation
copies in that closure are frozen release evidence, not a second editable
owner. Its provenance maps them back to `clients/*`. Update those owners and
recompose explicitly for a new native release; do not evolve both copies.

## What was consolidated

The GitHub development baseline is `9b4b3d1d33e68985b33b66597bde5009c8fa87fa`.
Most prior CosmaBot feature branches are already incorporated or patch-equivalent
to main. The actual gaps were the untracked iPhone composition, local UI edits,
and stale handoff/source descriptions. This branch preserves those gaps without
merging old release branches over newer main changes.

The local recovery captures 17 tracked UI modifications and three new
provider-portal files from the old release checkout, plus a separate connector
search alias patch. Authorship is unknown. Review these against current main
with a three-way comparison; both patches touch SettingsHub. See
`docs/recovery/20261030/README.md` and `MANIFEST.json`.

Unfinished hosting helpers and the superseded Core read API remain historical
recovery material in the private handoff. They are not runtime integrations to
activate. Separate Core/Scribe/Session Prep/Zoom repositories and services were
not changed by this consolidation.

## Released baseline and next work

See [the release ledger](COSMABOT_RELEASE_STATE_20261030.md). Development main is
newer than the released commit: neither main nor this recovery branch should be
labelled as the already-qualified 1107 binary. Source recovery is not a new
build, deployment or device acceptance result.

The November 1 technical-beta product goal remains the handoff objective:
Chief-first native/mobile usability, approachable connectors and complete
synthetic provider journeys. Broad execution was paused at the owner's request
when 1107 TestFlight delivery and hosted R6r1 activation finished. This source
consolidation and PR230 review do not resume that execution automatically.

When the owner resumes product development, prioritize:

1. Reconcile preserved connector/provider UI changes against current main.
2. Qualify a portable iPhone composition from these owned sources and the
   current renderer; retire the old external source dependency before claiming
   a reproducible native build.
3. Exercise end-to-end synthetic provider journeys and improve the mobile UX;
   complete real vendor access requirements without claiming synthetic adapters
   are live integrations.
4. Finish native installed-version/device checks and remaining launch gates
   against a single exact reviewed commit; record source/binary/runtime identity.

Use `CURSOR_HANDOFF.txt` as the local/cloud starting prompt. Both modes work on
the same remote branch and exchange changes through Git commits/PRs.
