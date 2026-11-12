# Review policy

Approved by John Clemente on 12 Nov 2026. Changing this file needs John's yes.

## 1. Default reviewer: every PR, every pushed head
- The default reviewer is **GPT-6 Luna** (Azure deployment `pr-review-luna` on CosmasCode). It runs from the CTO box, never from GitHub Actions.
- It reviews the three-dot diff at the exact head, plus CI results and workflow files. It returns:
  - LIVE_USERS (line 1),
  - VERDICT PASS/HOLES,
  - numbered holes, each with severity, file:line and a fix.
- It reviews code only, never PHI. A pre-send scan refuses diffs that match SSN, MRN or DOB patterns or touch patient-fixture paths.
- Every run is logged with repo, PR, head, verdict, tokens and cost.
- Budget is about $20 a month. A likely overrun goes to John first.
- Until the shadow test passes (final readout 25 Nov 2026), Luna runs in shadow mode only. Fable stays the reviewer of record for anything Fable reviews today.

## 2. When Fable (Fable 5.2 Oracle, read-only, medium effort) is also required
Fable reviews **after** the default reviewer says PASS and required CI is green at the same head. That way Fable sees clean PRs.

### 2a. High-risk: sorted by the PR's file list. Any match makes it high-risk.

| Category | Matches (any changed path) |
|---|---|
| Patient data or deletes | `migrations/**`, `**/*patient*`, `**/*retention*`, `docs/RETENTION.md`, `scripts/*patient*`, `**/*delete*` in `src/**` |
| Sign-in, accounts, Clerk | `**/*clerk*`, `**/*auth*`, `clients/apple/native-auth/**`, `**/*keychain*`, `**/*signin*`, `docs/NATIVE_SIGNIN*` |
| Logging and redaction (code) | `src/**/*log*`, `src/**/*redact*`, `src/**/*scrub*`, `**/*audit*` (not test-only, see N1) |
| Secrets | `.env*`, `**/*secret*`, `**/*.op`, `**/*vault*`, `.envrc` |
| Infra, deploys, cost | `infra/**`, `**/*.tf`, `**/deploy*`, `.github/workflows/**` (except N3) |
| App Store and release | `**/Info.plist`, `**/PrivacyInfo.xcprivacy`, `**/*.entitlements`, `**/fastlane/**`, `scripts/compose-portable-iphone.py`, `scripts/prepare-owned-*`, `**/Release*` |
| Database | `migrations/**`, `**/*.sql`, `**/models.py`, `**/schema*` |
| Live-user access | `**/*enrollment*`, `**/*practice*`, `**/*invitation*`, `**/*baa*`, `**/*agreement*`, `**/*onboarding*`, `**/*billing*`, feature-flag or settings defaults (`infra/standalone/**`, `**/config.py`) |

### 2b. Hard: any one of these
1. **2 or more failed default-review rounds** (VERDICT HOLES) on the same PR.
2. **2 or more red CI runs on the same failure:** the same check or test fails at two different heads.
3. **Very large:** more than **1,500 changed lines** (additions + deletions) or more than **25 files**. This is about the 90th percentile of our PRs (30-day p90: 1,192 to 2,658 lines). Also any packet over the default reviewer's 150k-token cap.
4. The default reviewer reports CONFIDENCE: low, or the author disputes a High or Blocking finding.
5. A 3rd round of review on any PR.

## 3. Default reviewer alone: narrowings N1 to N5
These skip Fable even if a glob in 2a matches, unless a 2b rule fires.

| # | Scope | Still goes to Fable if... |
|---|---|---|
| N1 | Test-only PRs: only `tests/**` or `*.test.*`, with synthetic fixtures | it changes a test that protects a 2a category **and** removes or weakens an assertion |
| N2 | Docs and comments only | the docs are sign-in, release, realm or retention contracts (`docs/NATIVE_SIGNIN*`, `docs/operational-*`, `docs/RETENTION.md`) |
| N3 | CI changes that only add or tighten checks | the diff removes a job or step, or adds `continue-on-error`, `if: false`, `paths-ignore` or a skip, or touches Trivy, required checks or the ruleset |
| N4 | Re-check rounds after a Fable HOLES where the fix is docs, comments or counts only | the fix touches code |
| N5 | Simulator and synthetic test tooling | it touches Release config, Clerk or keychain, or anything reachable in a Release build |

What we accept by narrowing: less depth on test-only changes, rare doc and code mismatches, subtle CI weakening inside "additive" changes, and fresh issues Fable might have noticed on a re-check. The hard rules (2b) are the backstop.

## 4. Fable's upstream role
- **Plan review before coding.** On any ticket that will touch a 2a category, Fable reviews the ticket plan or design (read-only, medium effort) before the Build Lead, Plugin Specialist, Codex or Cursor agents start coding. Coding starts after Fable says PASS on the plan, or after the CTO accepts the named risks.
- **Coding rules.** Fable proposes refreshes to the "Coding rules from review findings" section in AGENTS.md, drawn from its findings. Changes go in by draft PR, with John's merge.
- **Weekly pattern review.** Every Thursday, Fable reads the past week's review ledgers, CI reds and default-reviewer HOLES. It reports the top repeat failures, proposes rule updates, and flags any narrowing that let a real problem through.
- **Strategic direction.** Fable writes a periodic strategic review across the three repos, like the one on 12 Nov 2026, at John's request.

## 5. Who does what
- **Release Lead:** sorts each PR by this file, runs the default reviewer, escalates to Fable under section 2, and keeps both ledgers (model, head, verdict, tokens).
- **Build Lead, Plugin Specialist, Codex, Cursor agents:**
  - Read the AGENTS.md coding rules before coding.
  - Wait for Fable's plan PASS on high-risk tickets.
  - Run the relevant tests before pushing, and push once per round.
  - Fix the default reviewer's HOLES before asking for Fable.
- **Nobody merges** without John's yes. An agent's say-so is never John's approval.
