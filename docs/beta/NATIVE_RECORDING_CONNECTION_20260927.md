# Native recording account and connection

The native authentication owner now derives a stable recording-account digest
from its own issuer, audience, origin, identity-policy flags, user and required
organization. A renewed SDK session keeps the same digest, while an obsolete
auth revision or blocked sign-out state cannot obtain it. This is a namespace
for later native key custody, not a credential or permission.

The native connection reads `native_recording_context` through the existing
fixed-origin CosmaBot workspace API. Only the native initializer constructs this
request; the generic renderer action initializer rejects it. The response must
match the requested workspace/session, expected operation, strict versioned
receipt shape and active recording status. The connection rechecks native auth
after the request; the OS API checks Core binding, nonce, freshness and current
workspace authority. No caller-supplied Scribe tenant or provider URL is used.

This adapts the account-digest and context-validation approach from Scribe's
native-auth sources at `ec511ff1c3b979901e80f5033c1f02a05f65c4b3`, preserving
CosmaBot's mandatory organization and its own workspace transport. It does not
import Scribe's optional-organization identity policy or direct Core mount API.

These connection methods prepare the native recorder integration. The native
host, encryption/queue custody, renderer selection and retained-recording
recovery still need coordinated integration before enabling that recording path.
This change creates no keys or recordings and changes no installed application.
