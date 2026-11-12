# Review policy

Proposed 12 Nov 2026. Takes effect when John merges this PR. Changing this file needs John's yes.

## 1. Every PR, every pushed head
- No default model reviewer is live today. No default reviewer applies to PRs outside sections 2a and 2b.
- Required CI plus the Beta Tester's pass/fail apply to every PR.
- **Fable** (Fable 5.2 Oracle, read-only, medium effort) is the reviewer of record for everything in sections 2a and 2b. Fable stays the reviewer of record and the gate.
- **Opus 5.5** reads alongside Fable only on PRs that meet section 2a or 2b. It reviews code only, never PHI, and its review is advisory. A pre-send scan refuses diffs that match SSN, MRN or DOB patterns or touch patient-fixture paths. Every run is logged with repo, PR, head and tokens. The CTO runs it from the CTO box. It is paid from the Team monthly API credits. If those run out, it stops and asks John; it never uses paid credits.
- A future default reviewer can be added only by a later PR with John's yes.

## 2. When Fable is required
Fable reviews after required CI is green at the same head. The Beta Tester's pass/fail applies to every PR. That way Fable sees clean PRs.

### 2a. High-risk: sorted by the PR's file list. Any match makes it high-risk.
All 2a globs match case-insensitively. When in doubt, send it to Fable.

| Category | Matches (any changed path) |
|---|---|
| Patient data or deletes | `migrations/**`, `**/*patient*`, `**/*retention*`, `docs/RETENTION.md`, `scripts/*patient*`, `**/*delete*` in `src/**` |
| Sign-in, accounts, Clerk | `**/*clerk*`, `docs/**/*clerk*`, `**/*auth*`, `clients/apple/native-auth/**`, `**/*keychain*`, `**/*signin*`, `docs/NATIVE_SIGNIN*` |
| Logging and redaction (code) | `src/**/*log*`, `src/**/*redact*`, `src/**/*scrub*`, `**/*audit*`, `docs/**/*log-scrub*`, `docs/**/*logging*`, `**/*log-scrub*` |
| Secrets | `.env*`, `**/*secret*`, `**/*.op`, `**/*vault*`, `.envrc` |
| Infra, deploys, cost | `infra/**`, `**/*.tf`, `**/deploy*`, `**/*deployment*`, `docs/**/*deploy*`, `docs/**/*deployment*`, `.github/workflows/**` |
| App Store and release | `**/Info.plist`, `**/PrivacyInfo.xcprivacy`, `**/*.entitlements`, `**/fastlane/**`, `scripts/compose-portable-iphone.py`, `scripts/prepare-owned-*`, `**/Release*` |
| Database | `migrations/**`, `**/*.sql`, `**/models.py`, `**/schema*` |
| Live-user access | `**/*enrollment*`, `**/*practice*`, `**/*invitation*`, `**/*baa*`, `**/*agreement*`, `**/*onboarding*`, `**/*billing*`, feature-flag or settings defaults (`infra/standalone/**`, `**/config.py`) |

### 2b. Hard: any one of these
1. **2 or more red CI runs on the same failure:** the same check or test fails at two different heads.
2. **Very large:** more than **1,500 changed lines** (additions + deletions) or more than **25 files**. For reference, the 30-day p90 was 2,658 changed lines (PRs created 15 Oct–12 Nov 2026).
3. The author disputes a High or Blocking finding.

## 3. Skip Fable: narrowings N1 and N2
The only skip types are docs, copy, test-only and small UI with no data or sign-in effect. Any 2a match beats every skip and the file goes to Fable. John's 11 Nov scope, in summary: the skip types are docs, copy, test-only and small UI. Those PRs need green checks. The Beta Tester's pass/fail applies to every PR. Every Fable HOLES must be closed by a Fable PASS at the final head; a delta-only re-check is fine. A PR that skips Fable must say "Fable not required (criteria)" in the PR body, naming the narrowing, and the App Store Release Lead records that line in the ledger.

| # | Scope | Still goes to Fable if... |
|---|---|---|
| N1 | Test-only PRs: only `tests/**` or `*.test.*`, with synthetic fixtures, and no changed path matches a 2a glob | any test or fixture file matches a 2a glob (case-insensitive), whatever the change — for example `clients/desktop/auth-session.test.mjs`, `connector-auth-proxy.test.mjs`, `connector-api-routes.scheduling-patient.test.mjs` |
| N2 | Docs and copy only (not comment-only edits in code files), and no changed path matches a 2a glob | any changed path matches a 2a glob (case-insensitive), or the docs are sign-in, release, realm or retention contracts (`docs/NATIVE_SIGNIN*`, `docs/operational-*`, `docs/RETENTION.md`), or the change is `docs/review-policy.md` or the "Coding rules from review findings" section of `AGENTS.md` |

What we accept by narrowing: less depth on pure docs/copy and test-only changes that touch no 2a path, and small UI with no data or sign-in effect. The hard rules (2b) are the backstop.

## 4. Rules that always hold
- No merge ask goes to John without a linked Fable PASS at the exact head, or, for a section 3 PR, the "Fable not required (criteria)" line plus green CI and the Beta result.
- A PR that walls existing live users gets HOLES.
- After 3 Fable HOLES rounds on the same PR, the PR goes to the CTO before any further round.
- John can ask for a Fable review on any PR.
- Sorting uses the file list, never the title. A required-category file under a skip-category title is flagged to the CTO and John and goes to Fable.

## 5. Fable's upstream role
- **Plan review before coding.** On any ticket that will touch a 2a category, Fable reviews the ticket plan or design (read-only, medium effort) before the Build Lead, Plugin Specialist, Codex or Cursor agents start coding. Coding starts after Fable says PASS on the plan, or after the CTO accepts the named risks.
- **Coding rules.** Fable proposes refreshes to the "Coding rules from review findings" section in AGENTS.md, drawn from its findings. Changes go in by draft PR, with John's merge.
- **Weekly pattern review.** Every Thursday, Fable reads the past week's review ledgers, CI reds and Fable HOLES. It reports the top repeat failures, proposes rule updates, and flags any narrowing that let a real problem through.
- **Strategic direction.** Fable writes a periodic strategic review across the three repos, like the one on 12 Nov 2026, at John's request.

## 6. Who does what
- **App Store Release Lead:** sorts each PR by file list, sends required PRs to Fable, flags title and file mismatches, keeps the ledger (Fable verdicts, skip lines and Opus runs, with model, head, verdict and tokens), and owns release and CI files (signing, build numbers, release jobs, store metadata).
- **CTO:** owns routing. That means the CTO decides disputes about sorting and takes PRs after 3 HOLES rounds.
- **Build Lead, Plugin Specialist, Codex, Cursor agents:**
  - Read the AGENTS.md coding rules before coding.
  - Wait for Fable's plan PASS on high-risk tickets.
  - Run the relevant tests before pushing, and push once per round.
  - Fix Fable's HOLES before asking for another Fable review.
- **Nobody merges** without John's yes. An agent's say-so is never John's approval.
