# Saved recording transcription and explicit consent recovery

Owner scope: resume transcription integration, perform the completed flow twice,
review one pass for optimization and one as a first-time provider. The October 10
instruction extends the work to Core/Scribe. Existing staging only; both visit
fixtures and audio are invented. Preserve all original recordings and history.

An old saved-source admission can conflict with the visit's other recording.
Select transfer and operations by the exact recording/session. Core PR748 provides
the receiver first; this sender carries its stable recording hash and requests
only exact legacy retry recovery. Unknown sessions are denied before network I/O.

Only Core's definite expired-consent/no-admission response permits a fresh user
confirmation. Keep the original transfer, append the new request and retain an
immutable rejection receipt. A lost reply never permits replacement consent.
The encrypted device journal retains every attempt and retries the latest exact
request after reopening. Add clip date/duration and move focus to transcription.

Migration bfdb4a6487c0 removes only the per-workspace uniqueness constraint and
adds immutable attempt/rejection tables. Keep per-recording and session identity.
Rollback means disable the flow while retaining expanded schema and every row;
do not delete audio, rewrite consent, unbind recordings or destructively downgrade.

Validate real migrated PostgreSQL with signed provider requests: separate clips
in one visit, reopening either session, lost replies, explicit renewal, revocation,
source changes and append-only history. Validate renderer behavior and closed
adapter contracts. Record exact final commit, results and implementer review in
the PR before merge. Release receiver/schema before sender and desktop renderer,
preserving the existing public profile, secrets and unrelated runtime settings.

Actual saved audio upload, transcript review, edited note save/reopen and both
provider walkthroughs remain pending until observed in the installed app.
