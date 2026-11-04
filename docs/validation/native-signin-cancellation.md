# Native sign-in cancellation

An unfinished secure sign-in window no longer leaves the Apple/Mac welcome
screen without an exit until the native 180-second deadline. The screen offers
**Cancel sign-in**, using the existing native sign-out operation, and shows
**Signing out** while that operation settles. Failed cancellation remains on
the existing explicit sign-out recovery path.

The renderer allows only sign-out to overlap an unfinished sign-in. A per-action
owner prevents the older sign-in from clearing a newer cancellation or replacing
its recovery state. A session read begun before the action is drained before a
fresh native state becomes the final check. No workspace request or token is
released while the owning action remains pending.

The native driver, issuer/subject/organization checks, SDK state and PKCE,
durable access block, expiry checks, token policy, and 180-second deadline are
unchanged. Native sign-out already fences a concurrent hosted sign-in. The
system sign-in window still has its own Close/Cancel control; the app action
cancels the account attempt through the existing native owner.

Focused synthetic validation: 58 tests passed in
`NativeAuthenticatedWorkspace.test.tsx`,
`NativeAuthenticatedWorkspace.foreground.test.tsx`, and
`DesktopAuthenticatedWorkspace.test.tsx`; TypeScript validation passed.
The added journeys cover cancellation, duplicate clicks, late successful/failed
sign-in, failed cancellation and explicit retry, a pre-cancellation session
read, and adapter replacement. Existing token, foreground, account, and logout
guards passed in the same affected suites.

This is a source/UI qualification. A freshly delivered native build and an
operational provider sign-in journey are still required for device acceptance.
