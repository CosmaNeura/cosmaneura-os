# CosmaBot November 1 launch manifest

This is a launch record for the CosmaBot November 1 technical beta. It was
read from `main` at commit `c4a04c7feac8268a43f01f79256232ae6bb9a3ec`
(`Allow beta.cosmas.ai as a second synthetic address`, pull request 242).
That commit is the evidence snapshot. It is not a released November 1
binary, image digest, or host release id.

This file does not deploy software, change sign-in, or invite anyone.

## Statements this launch must keep

EHR is synthetic only.

For Zoom, tell users "use Upload Recording". Never say Zoom is "fixed".

There is no SOC 2.

There is no EHR write-back.

There is no stranger checkout, meaning no self-serve purchase by unknown users.

## How to read the capability list

A row below is included only when a file on that `main` commit says it.
"Ships" means the source can build it, or a release ledger already recorded
it. It does not mean a vendor accepted it, a tester was invited, or this
commit is the November 1 install. Where two records disagree, both are
cited and the choice is left under Open questions.

## A. What is in the tree for this launch

### No November 1 package is named

`docs/COSMABOT_SOURCE_OF_TRUTH.md` calls the November 1 technical-beta
product goal the handoff objective: Chief-first native and mobile
usability, approachable connectors, and complete synthetic provider
journeys. The same file says broad execution was paused after 1107
TestFlight delivery and hosted R6r1 activation, and that source
consolidation does not resume that execution. It also says remaining
launch gates are not marked complete.

`docs/COSMABOT_RELEASE_STATE_20261030.md` says development `main` is newer
than the released commit, and that neither `main` nor the recovery branch
should be labelled as the already-qualified 1107 binary.

### Last recorded release ledger

These figures are copied from `docs/COSMABOT_RELEASE_STATE_20261030.md`.
They identify the October 30 ledger. They are not relabelled here as the
November 1 install.

| Item | Recorded checkpoint | Limit recorded in that ledger |
| --- | --- | --- |
| Released source | `0e70fe6a802ab30362ffb77e8cb8538f7123bc1c` | Pull request 222 merged as `cc3111cc271a848224b5c30c7ed7734879e1699c`; recorded source and `main` CI passed |
| Development `main` at that capture | `9b4b3d1d33e68985b33b66597bde5009c8fa87fa` | Newer than the 1107 binaries |
| iPhone and macOS version | `0.1.147 (1107)` | Signed iPhone upload and notarized Mac artifact recorded |
| TestFlight | 1107 processed and Testing in CosmaBot Beta | Physical iPhone 1107 installation was not directly verified; last direct phone check was 1106 |
| Local Mac app | Last directly verified native desktop was 1105 | App Store Connect 1107 install telemetry does not prove the local native app was replaced |
| Hosted release | `release-r6r1` activation, trial, and verification passed October 29 | Web advanced to 1107; API reused R5 source `b770fe05f339e15c681a0df2b4b4b329e47d770d`; no data, schema, or identity change |

Artifact hashes for that ledger live in the same file. This manifest does
not repeat them.

### Operational beta client the source can build

`docs/operational-beta-build.md` selects
`VITE_WORKSPACE_FEATURE_PROFILE=operational-beta-v1`. It says that profile
includes:

- appointments
- intake, inbox, and handoff
- Scribe capture and note, source, correction, and recovery controls
- preparation and work
- the private bot team and AI activity
- routines
- membership
- messaging and fax
- payment, portal, and all implemented account connections

The same file says Athena remains read-only, and that server readiness,
access grants, service enablement, and per-action human approval still
control actual use. Capture mode is one of `browser_microphone` (web and
desktop), `ios_native` (Apple), or `synthetic` (synthetic-only
development). Choosing a source stages its Scribe adapter and does not
start recording.

`clients/shared/beta-feature-profile.mjs` is the profile implementation.
For `operational-beta-v1` it sets the flags in `BETA_FEATURE_FLAGS` and
sets `athenaAccess` to `read_only`. Pilot flags, including
`VITE_EHR_READ_ENABLED`, `VITE_MESSAGES_ENABLED`,
`VITE_CALENDAR_IMPORT_ENABLED`, and `VITE_MICROSOFT_MESSAGE_ENABLED`, are
on only when the build sets each one to `true` or `false` explicitly.
Patient scheduling setup (`VITE_WORKSPACE_SCHEDULING_PATIENT_SETUP_ENABLED`)
is set to `false`. The profile comment says the receiver remains
unqualified and the correspondence capability ships dark.

Clients named by that resolver are `web`, `desktop`, and `apple`.
`docs/operational-beta-build.md` says `Dockerfile.web` uses this same
profile, and that the build tools do not install, sign, qualify a release,
or launch an app.

`README.md` describes CosmaBot as a standalone desktop and mobile app whose
workspace combines private notes, chat, team settings, research, and
tracked operational work. `docs/COSMABOT_SOURCE_OF_TRUTH.md` names the
integrated areas and the files that hold them: Chief-first Messages,
practice and settings, EHR and task flows, email, calendar, research, and
fax, the independent Cosmas MD practice, the Mac shell, and the recovered
iPhone project under `apps/capture`. That index says source presence does
not establish live vendor acceptance, and that separate Core, Scribe,
Session Prep, and Zoom repositories were not changed by the consolidation.

### EHR

EHR is synthetic only.

Evidence on this commit:

- `docs/elation-read-integration.md` says the Elation appointment and
  clinical-record review milestone is synthetic only and off by default.
  Production configuration is rejected. Qualification uses invented
  responses. No vendor account was created or contacted.
- `docs/beta/EHR_CONNECTOR_WORKSTREAM_20261025.md` says the phone delivery
  it records uses invented provider data, the clinical runtime remains
  default-off and MockTransport-only outside the synthetic preview, and
  live EHR access is not enabled.
- `clients/shared/beta-feature-profile.mjs` records Athena access for this
  profile as `read_only`.

There is no EHR write-back.

The connector workstream says no external clinical read, prescription, or
writeback is enabled for the Tebra path it describes, and that prescription
transmission and clinical writeback remain separate work. Elation's
problem-list and medication reads, in `docs/elation-read-integration.md`,
do not authorize prescribing. `docs/tebra-fhir-read.md` says reconciliation,
prescriptions, and clinical writeback are separate work.

Older records still say the EHR connector is dark:
`docs/CAPABILITY_MATRIX.md` and
`docs/beta/SYNTHETIC_LAB_CAPABILITY_MANIFEST.md`. Those files were not
rewritten by the operational beta profile. Which record governs the
November 1 tester surface is an open question. None of them authorizes
write-back, and none of them authorizes a live production EHR.

### Zoom

Desktop meeting audio can name a Zoom window. `docs/beta/ENCOUNTER_QUICK_START_20260929.md`
says one further action selects the Zoom or Chrome window.
`clients/desktop/native-audio/README.md` and
`clients/desktop/recorder/native-process-driver.ts` accept the bundle
`us.zoom.xos` as a meeting-audio application. That source does not say the
Zoom path is fixed.

For Zoom, tell users "use Upload Recording". Never say Zoom is "fixed".

A search of this commit did not find a control whose label is
`Upload Recording`. Saved-recording screens use other words, including
"Transcribe your saved recording" in `web/src/SavedRecordingTranscriptionPanel.tsx`
and "Use a Scribe recording" in the encounter quick start. Which control
the spoken instruction points at is an open question. The words to say are
not.

### Not in this launch

There is no SOC 2. This repository has no SOC 2 report.

There is no stranger checkout, meaning no self-serve purchase by unknown
users. `docs/CAPABILITY_MATRIX.md` lists patient payment and PAN as dark
and forbidden in v1. `docs/beta/SYNTHETIC_LAB_CAPABILITY_MANIFEST.md` lists
payment and PAN as forbidden. `docs/beta/CONNECTOR_UX_AND_ACTIVATION_20260928.md`
describes a Stripe test-mode PaymentIntent that is not a complete hosted
payment-link flow. The operational beta profile still turns
`VITE_FINANCE_SETUP_ENABLED` and `VITE_FINANCE_WORK_ENABLED` on. That is
not stranger checkout. Whether those finance screens are shown to an
invited tester on November 1 is an open question.

`docs/beta/SYNTHETIC_LAB_CAPABILITY_MANIFEST.md` records PHI as not
authorized and the deployment mode as `synthetic_lab`. `README.md` says
repository fixtures remain invented. This manifest does not record a
clinic, a BAA, or a PHI authorization.

`docs/beta/CAPABILITY_MANIFEST_TEMPLATE.md` and the synthetic-lab manifest
still list real email, SMS, Teams, external model calls, Track A Scribe,
and automatic send as dark or forbidden. `docs/operational-beta-build.md`
is newer and includes messaging, fax, and account-connection UI in the
client profile. Live delivery still needs the grants that file names.
Which of those connector states is the November 1 runtime is an open
question.

## B. Rollback

Two different rollbacks are recorded. The host pointer selects which
release directory `start.sh` runs. App builds are rolled back by installing
an earlier package or by moving image digests. This manifest does not name
the previous release directory or the previous app build.

### Host pointer

After preparation, `infra/beta/vm/runtime/README.md` says to install
`cosmabot-staging.service` with a root-owned
`/etc/cosmabot/active-release` containing only the canonical public
release directory.

`infra/beta/vm/runtime/cosmabot-staging.service` loads that file and runs:

```text
ExecStart=/bin/sh ${RELEASE_DIR}/start.sh ${RELEASE_DIR} run
ExecStop=/bin/sh ${RELEASE_DIR}/start.sh ${RELEASE_DIR} stop
```

The service comment says the file contains only
`RELEASE_DIR=/opt/cosmabot/releases/<id>`.

`infra/beta/vm/runtime/start.sh` runs only as root on Linux. It takes the
absolute release directory and one action: `data`, `prepare`, `run`, or
`stop`. `run` starts the full runtime. `stop` stops the Compose project
`cosmabot-staging` with a 120 second timeout and does not delete data.
The script holds `/run/cosmabot/runtime.lock`. If that lock is taken, it
exits and leaves the other operation running.

Do not edit files inside a release directory. The runtime readme says not
to rewrite an existing immutable release.

To point the host at the previous release and run its `start.sh`:

1. Stop the current release while `/etc/cosmabot/active-release` still
   names it, so stop uses that release's script. Either
   `systemctl stop cosmabot-staging.service`, or, as root,
   `<current-release>/start.sh <current-release> stop`.
2. Replace `/etc/cosmabot/active-release` with a root-owned file whose
   only line is `RELEASE_DIR=` followed by the previous release's
   canonical directory under `/opt/cosmabot/releases/`.
3. Run that previous release's `start.sh` with `run`. Starting
   `cosmabot-staging.service` does this, because `ExecStart` is
   `${RELEASE_DIR}/start.sh ${RELEASE_DIR} run`. The direct form is
   `<previous-release>/start.sh <previous-release> run`.

`infra/beta/vm/backup/install-host.py` accepts an active-release line only
when it matches
`RELEASE_DIR=/opt/cosmabot/releases/stg-owner-20260925-r<digits>`.
The staging unit comment allows a general `<id>`. Whether the previous
November 1 directory uses the backup installer's name is an open question.

### App builds

Hosted API and web images roll back by digest.
`docs/beta/WEB_RELEASE.md` says rollback is another reviewed plan that
changes `web_image_digest` and/or `image_digest` to a previously scanned
digest. Do not rebuild an old tag, and do not change Clerk authority as a
rollback shortcut.

`infra/beta/README.md` records the protected-runner operation
`release-rollback` for two already built, scan-clean releases whose API
digests differ and whose web digests differ. The same file says database
changes stay forward-only: if the prior application digest is not
compatible with schema head, use `release-forward` and a tested correction
instead of downgrading or restoring over the live database.
`docs/RELEASE_AND_ROLLBACK.md` says the same for the prepared D3 boundary.
The previous digests for November 1 are not in this repository.

Desktop builds have no automatic download.
`clients/desktop/desktop-update-guidance.mjs` says a desktop update is a
matching CosmaBot package supplied by the practice: keep saved drafts and
recordings, quit CosmaBot, install the supplied package, reopen, and check
the workspace connection. `docs/desktop-release-packaging.md` says
`CosmaBot → Update CosmaBot…` explains that manual path, and
`CosmaBot → About CosmaBot` shows the installed version. Rolling back a
desktop build uses that same path with the earlier matching package. The
repository does not name that earlier package.

iPhone rollback steps are not in the repository. The October 30 ledger
records TestFlight build 1107 as processed and in Testing, and says the
last direct phone check was 1106. It does not say how to point testers at
a previous build.

## C. Monitoring

The watches below are what the staging source records. The probe and its
runtime alerts are off until `runtime_monitoring_enabled` and
`runtime_alerts_enabled` are set. Both default to false in
`infra/beta/vm/foundation/runtime_monitoring.tf`. This manifest does not
record that they are enabled on a live host.

| Watch | What the source checks | How often | Who is notified |
| --- | --- | --- | --- |
| Health probe | `infra/beta/vm/monitoring/probe.py`, started by `cosmabot-health.service`. It reports only `application` and `backup` as `ok` or `failed`, plus `observed_at`. It checks the six containers `api`, `worker`, `web`, `proxy`, `postgres`, and `redis`, fresh Docker health, the local TLS listener, and the backup receiver, timers, and latest successful backup status job. It does not forward command output, health bodies, application logs, credentials, or records. | `infra/beta/vm/monitoring/cosmabot-health.timer`: 90 seconds after boot, then every 60 seconds (`OnUnitActiveSec=60`), with `AccuracySec=5`. | The probe runs as root and writes a journal line identified as `cosmabot-health` on facility `local6`. It does not itself page a person. |
| API `/ready` | The rendered API healthcheck in `infra/beta/vm/runtime/render.py` requests `http://127.0.0.1:8000/ready` from inside the API container. The worker healthcheck requests `http://127.0.0.1:8001/ready`. The minute probe treats the app as unhealthy unless that Docker health log succeeded and ended within 90 seconds. Caddy on the public API hostname responds 404 for `/ready` (`render.py` private paths). The public URL is not the probe. | Container healthcheck interval 15 seconds, timeout 5 seconds, 3 retries, start period 60 seconds. Included in the minute probe. | Same health report as the probe. No separate sign-in or readiness mailbox is named. |
| Web | The web container healthcheck requests `http://127.0.0.1:8080/healthz`. The probe also opens TLS to `127.0.0.1:443` as `staging.cosmas.ai` and requires HTTP 200 and a `text/html` content type. | Web container healthcheck interval 15 seconds, timeout 5 seconds, 3 retries. The TLS check runs once per probe. | Same health report as the probe. |
| Sign-in | `docs/beta/WEB_RELEASE.md` says a human verifies production Clerk login, Beta Lab organization membership, and authenticated API access with invented data after a workload apply. No probe, timer, or test in `infra/beta/vm/monitoring/` requests a sign-in. | No interval is recorded. | No person is named. |

When runtime alerts are enabled, two scheduled query rules
(`alert-cbot-application-eus2-lab01` and `alert-cbot-backup-eus2-lab01`)
evaluate every minute over a 10 minute window. Each fires when its health
state has had no successful report for five minutes, including a stopped
probe, agent, or ingestion path. They call action group
`ag-cosmabot-staging-eus2-lab01`. The email receiver in
`infra/beta/vm/foundation/monitoring.tf` is named `staging-owner`. The
address is `var.alert_contact_email` and is not stored in this repository.
`infra/beta/vm/monitoring/README.md` calls that notification paging the
owner. The same action group receives the VM availability, CPU, and OS-disk
IOPS metric alerts. Those metric alerts evaluate every minute. Their
windows are 5 minutes for availability and 15 minutes for CPU and disk.
They do not check `/ready`, the web page, or sign-in.

The probe's TLS check is hardcoded to `staging.cosmas.ai`.
`infra/beta/vm/runtime/render.py` on this commit also accepts
`https://beta.cosmas.ai` with `https://api.beta.cosmas.ai`, and refuses
every other hostname. `infra/beta/README.md` says synthetic mode stays on
and nothing is deployed by that acceptance. Whether the November 1 host
uses `staging.cosmas.ai` or `beta.cosmas.ai` is an open question. The
probe as written does not check `beta.cosmas.ai`.

## Open questions

1. Which commit, image digests, desktop package, and TestFlight build are
   the November 1 install? `main` at the commit above is not identified as
   that install. The October 30 ledger's 1107 and `release-r6r1` records
   are explicitly not a label for current `main`.
2. What is the previous `/opt/cosmabot/releases/<id>` directory, and does
   its name match the backup installer's `stg-owner-20260925-r<digits>`
   pattern?
3. Are the previous API and web digests compatible with the schema head
   that will be running on November 1? The recorded rule is to avoid a
   database downgrade when they are not. This repository does not say
   which case applies.
4. Which earlier Mac package and which earlier iPhone TestFlight build are
   the app-build rollback targets, and what is the iPhone rollback
   procedure? Desktop rollback is "install the earlier matching package."
   iPhone steps are not written down here.
5. Are `runtime_monitoring_enabled` and `runtime_alerts_enabled` on for the
   host that serves this launch? The source defaults are false. The
   `alert_contact_email` value is not in the repository, so the person
   behind `staging-owner` is not named here.
6. Who watches sign-in, and how often? Clerk login is a release
   verification step in `docs/beta/WEB_RELEASE.md`. It is not a probe.
7. Which web hostname is in use, `staging.cosmas.ai` or `beta.cosmas.ai`?
   The health probe's TLS check names only `staging.cosmas.ai`.
8. Which control should a person click for "use Upload Recording"? That
   label is not in this commit. The Zoom and Chrome window picker is.
9. Which EHR and connector record governs November 1: the operational beta
   profile (Athena read-only, messaging and fax included, EHR read only if
   the pilot flag is set), or the older synthetic-lab and capability-matrix
   rows that leave Athena, Acuity, and EHR dark? EHR stays synthetic
   either way, and write-back stays off either way.
10. Are the finance screens in the operational beta profile visible to
    invited testers? They are not a stranger checkout. The repository does
    not say whether they are part of the November 1 tester surface.
