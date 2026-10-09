# Scribe startup read overlap

Tier 2: authenticated startup and private draft readiness. This changes read
scheduling, not authentication, server authorization, consent or audio custody.

After the existing compatibility gate accepts, access, setup and provider-team
GETs may run concurrently through their existing authenticated API paths. The
team response is exposed only when both practice reads accept. The joined
startup has a 15-second limit. A pending or denied practice still renders its
access gate without consuming private team data.

EncounterWorkspace consumes the accepted team result once, for the same
identity and protocol generation, before its deadline. Its existing encrypted
journal preparation then runs. Later Home, Scribe and recovery authorization
reads remain fresh. GET consumers may share an unresolved provider-team read;
settled results and errors are never cached. Writes retain their original paths.

Each shared-read subscriber owns cancellation. Cancelling the last subscriber
aborts the underlying request. Protocol changes abort every subscriber; native
account validity is checked before dispatch and before response delivery.
Responses are cloned per consumer so mutable team drafts remain separate.

Local acceptance covers overlap, one-use handoff, remount, identity replacement,
native revocation, protocol blocking, access denial, independent cancellation,
last-subscriber abort, fresh dispatch after settlement, deadline refusal,
existing notebook preservation and private recording controls. TypeScript and
the production renderer build must pass. Record exact committed source and
commands in the PR. Implementer review is not independent review or GitHub
approval.

Recovery: revert this source change and rebuild the renderer. The API contracts,
native helpers, profiles, scopes, entitlements, databases and encrypted stored
data are unchanged. No migration, token cache, audio upload, transcription,
external action or new microphone permission is introduced.

Source merge is separate from activation. The installed Mac/iPhone 1050
candidates and hosted e281 renderer precede this change. Actual fresh sign-in
to recording must still be measured separately on desktop and iPhone, including
human consent and OS permission time. Passing local tests is not evidence of
the 5–7-second hardware target.
