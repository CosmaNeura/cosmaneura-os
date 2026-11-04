# Native ready-practice choice recovery

Prepared in the isolated local clone
`/private/tmp/cosmabot-practice-choice-recovery-20261104`, based on
`ca8ff3a1147f788c3daddc8138c073cf23ddd0af` for integration into PR 284.

The enrollment revision combines the account counter and the currently selected
practice counter. A successful practice switch can therefore produce an equal
or lower revision. After a lost selection reply, a fresh status and membership
read now resolves the saved choice when both identify the desired ready practice.
Checking never opens the native workspace; the user must explicitly select
**Open Chief**. A retry preserves the original idempotency key only while the
original practice ID (including no current practice) and expected revision remain
unchanged. An unrelated current practice requires a fresh choice and key.

Validation on the changed source, using existing resident dependency symlinks:

- `node node_modules/vitest/vitest.mjs run src/NativeEnrollmentEntry.test.tsx`
  from `web`: **1 file passed, 21 tests passed**. The parameterized lost-success
  cases cover higher, equal and lower composite revisions and require no second
  selection or native activation before explicit Open. A separate case proves
  an unrelated selected practice at the same composite revision requires a new
  choice and idempotency key; the existing unchanged-original case still retries
  the exact prior request and key.
- `node node_modules/typescript/bin/tsc --noEmit -p tsconfig.json`
  from `web`: **passed**.
- `git diff --check`: **passed**.

The initial local check lacked the existing capture dependency symlink and could
not resolve its imports. Reusing that resident dependency tree allowed the checks
above to pass; no dependency installation or configuration change was needed.

This qualification covers the focused UI suite and TypeScript project check.
The 13 required CI runs must qualify the integrated new PR head separately.
The frozen `ca8ff3a` candidate remains unpublished. This change does not alter
native authority or plugin contracts and includes no SDK run, signing, release,
image, host, Core or Scribe operation.
