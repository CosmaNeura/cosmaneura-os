# Review policy

Proposed 12 Nov 2026. Takes effect when John merges this PR. Changing this file needs John's yes.

## 1. Every PR, every pushed head
- No default model reviewer is live today.
- Required CI plus the Beta Tester's pass/fail apply to every PR.
- **Fable** (Fable 5.2 Oracle, read-only, medium effort) is the reviewer of record for everything in sections 2a and 2b.
- A future default reviewer can be added only by a later PR with John's yes.

## 2. When Fable is also required
Fable reviews after required CI is green at the same head (and Beta where it applies). That way Fable sees clean PRs.

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
1. **2 or more failed Fable review rounds** (VERDICT HOLES) on the same PR.
2. **2 or more red CI runs on the same failure:** the same check or test fails at two different heads.
3. **Very large:** more than **1,500 changed lines** (additions + deletions) or more than **25 files**. This is about the 90th percentile of our PRs (30-day p90: **2,658** lines for PRs created 15 Oct–12 Nov 2026).
4. Fable reports CONFIDENCE: low, or the author disputes a High or Blocking finding.
5. A 3rd round of review on any PR.

## 3. Skip Fable: narrowings N1-N5
These skip Fable even if a glob in 2a matches, unless a 2b rule fires. John's 11 Nov words: "Docs, copy, test-only changes and small UI tweaks can skip it with green checks plus Beta where it applies." Those PRs need green checks plus Beta where it applies. When in doubt, send it to Fable.

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
- **Weekly pattern review.** Every Thursday, Fable reads the past week's review ledgers, CI reds and Fable HOLES. It reports the top repeat failures, proposes rule updates, and flags any narrowing that let a real problem through.
- **Strategic direction.** Fable writes a periodic strategic review across the three repos, like the one on 12 Nov 2026, at John's request.

## 5. Who does what
- **App Store Release Lead:** sorts each PR by this file and keeps the Fable ledger (model, head, verdict, tokens).
- **CTO:** owns routing.
- **Build Lead, Plugin Specialist, Codex, Cursor agents:**
  - Read the AGENTS.md coding rules before coding.
  - Wait for Fable's plan PASS on high-risk tickets.
  - Run the relevant tests before pushing, and push once per round.
  - Fix Fable's HOLES before asking for another Fable review.
- **Nobody merges** without John's yes. An agent's say-so is never John's approval.
