# Native sign-in and account contract (Mac / iPhone)

Stable production contract for CosmaBot Mac and iPhone apps after human sign-in
and enrollment. Apps learn the user's production Clerk Organization and practice
Box from the enrollment account service, then open that practice's own workspace.
This document freezes the fields and routes the native clients build against.

Product invariants this contract preserves:

- One legal Org equals one logical Box (`organization_id` ↔ `box_id`).
- Humans and agents are distinct principals; enrollment routes are human-only.
- JWT Organization claims never grant registry ownership by themselves.
- Agents cannot self-approve, impersonate humans, or open a human seat.

Contract versions:

| Surface | Value |
| --- | --- |
| Enrollment status / config | `enrollment.v1` |
| Native workspace profile | `cosmas-native-workspace-profile.v1` |
| Active native workspace host snapshot | `cosmabot.native-active-workspace.v1` |

Do not invent a second tenant id. After a ready entitled membership, the apps
treat `workspace.organization_id` (Clerk Org) and `workspace.box_id` (Box) as the
paired production practice identity.

## Environments and hosts

| Mode | Enrollment `data_mode` | Profile `data_mode` | Identity profile | Clerk frontend | Practice web host | Practice API host |
| --- | --- | --- | --- | --- | --- | --- |
| Synthetic staging | `synthetic` | `synthetic` | `operational-staging-v1` | `*.clerk.accounts.dev` (or dedicated staging Clerk) | `https://<practice_uuid>.staging.cosmas.ai/chief` | `https://api.<practice_uuid>.staging.cosmas.ai` |
| Production / authorized beta | `production` | `authorized_beta` | `operational-beta-v1` | `https://clerk.beta.cosmas.ai` | `https://<practice_uuid>.workspace.cosmas.ai/chief` | `https://api.<practice_uuid>.workspace.cosmas.ai` |

Account-service hosts (not practice workspaces):

| Environment | Account web | Enrollment API |
| --- | --- | --- |
| Staging | `https://onboarding.staging.cosmas.ai` | `https://enrollment-api.staging.cosmas.ai` |
| Production | `https://app.cosmas.ai` | `https://enrollment-api.cosmas.ai` |

Production enrollment API host is pinned: **`enrollment-api.cosmas.ai`**. Native
clients call that origin for `/enrollment/v1/native/*` in production. Do not
substitute another hostname.

Native request origins (exact `Origin` header on every native enrollment call):

| Client | Origin |
| --- | --- |
| iPhone (`apple`) | `capacitor://localhost` |
| Mac (`desktop`) | `app://cosmas` |

Production native sign-in requires a non-empty Clerk session `aud` that matches
the configured enrollment / workspace audience. Native tokens may omit `azp`;
when `azp` is present it must equal the native origin above. Browser sessions
still require `azp`.

## Identity the app must present

Every authenticated native enrollment request:

```http
Authorization: Bearer <Clerk session JWT>
Origin: capacitor://localhost   # or app://cosmas
```

Required JWT claims (enrollment verifier):

| Claim | Rule |
| --- | --- |
| `iss` | Exact pinned Clerk issuer for the environment |
| `sub` | Clerk user id (`user_…`) |
| `sid` | Live Clerk session id (`sess_…`) |
| `exp` / `iat` / `nbf` | Required; small leeway allowed |
| `aud` | Required and exact when the environment configures a non-empty audience (production); must be **absent** when audience is empty (development shared-staging style) |
| `azp` | Optional for native; if present must equal the request `Origin` |

The verifier then confirms the Clerk session is active and the user's primary
email is verified. Registry membership / role / billing come from enrollment
storage, not from unverified JWT email or Org claims alone.

Do not send `X-Box-Id`, `X-Actor-Principal-Id`, query strings, content encoding,
or transfer encoding on native enrollment identity calls.

## How the app learns org and practice

Happy path after the human already has a ready, entitled practice membership:

1. Sign in with Clerk using the native SDK for the selected realm.
2. `GET /enrollment/v1/native/config` — confirm enrollment is enabled for this
   origin and read `native_account` (issuer, audience, session policy, origin).
3. `GET /enrollment/v1/native/status` — read stage, selected practice, and any
   already-bound `workspace.organization_id` / `workspace.box_id`.
4. If the human belongs to more than one practice: `GET /enrollment/v1/native/practices`
   then `POST /enrollment/v1/native/select-practice` with `Idempotency-Key`.
5. When status `stage === "ready"` and workspace proofs are present:
   `POST /enrollment/v1/native/workspace-profile` with a fresh UUID `nonce`.
6. Validate the response with the shared
   `validateRegisteredNativeProfile` contract (`clients/shared/native-practice-profile.mjs`
   / Swift `NativePracticeProfile`).
7. Activate Clerk Organization `nativeIdentity.organizationId`, then open
   `workspace.url` against `nativeIdentity.apiOrigin` for that practice only.
8. Explicit user action opens Chief; discovery alone must not navigate.

New enrollment (no practice yet) uses the same native `/enrollment/v1/native/*`
mutators as the browser flow (`profile`, `practice`, `baa/*`, `checkout`,
`workspace/confirm`, …). Checkout and activation remain gated; a return URL
never grants access by itself.

## Endpoints (stable for native clients)

Base path: `/enrollment/v1`. Prefer the `/native/…` siblings; they enforce the
native origin dependency and never fall back to browser `azp` rules.

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/native/config` | Origin only | Public config + `native_account` |
| GET | `/native/status` | Bearer + Origin | Selected practice enrollment status |
| GET | `/native/practices` | Bearer + Origin | Membership list + `active_practice_id` |
| POST | `/native/select-practice` | Bearer + Origin + Idempotency-Key | Switch active practice |
| POST | `/native/workspace-profile` | Bearer + Origin | **Stable production identity handoff** |
| PUT | `/native/profile` | Bearer + Origin + Idempotency-Key | Save human profile |
| PUT | `/native/practice` | Bearer + Origin + Idempotency-Key | Create/update practice draft |
| GET/POST | `/native/baa/current`, `/native/baa/accept`, `/native/baa/receipt` | Bearer + Origin | Agreement |
| GET | `/native/quote` | Bearer + Origin | Current quote (from status) |
| POST | `/native/invitations`, `/native/join` | Bearer + Origin + Idempotency-Key | Seats / join |
| POST | `/native/checkout`, `/native/recover`, `/native/portal` | Bearer + Origin + Idempotency-Key | Billing (TEST/live per env flags) |
| POST | `/native/workspace/confirm` | Bearer + Origin + Idempotency-Key | Measure workspace readiness |

Probe routes (not account identity): `GET /health`, `GET /operational-ready`,
`GET /ready`.

### `GET /native/status` — activation / enrollment exposure

`contract_version`: `enrollment.v1`.

| Field | Meaning |
| --- | --- |
| `revision` | Composite account + selected practice revision |
| `stage` | `account` \| `practice` \| `agreement` \| `activation_pending` \| `payment` \| `finishing_setup` \| `ready` \| `negotiated` \| `payment_action_required` \| `canceled` |
| `profile` | `{ display_name, title, email }` or null while empty |
| `practice` | Practice row including `id`, names, address, `human_seats`, `role` (`owner`\|`admin`\|`staff`), `covered_entity`, `can_sign` |
| `agreement` | Acceptance flag + document identity + `receipt_id` |
| `quote` | Seat quote or null |
| `billing` | `{ status, trial_ends_at, first_charge_at, cancel_at_period_end, payment_action_required }` |
| `workspace.status` | `pending` \| `provisioning` \| `ready` \| `failed` |
| `workspace.url` | Set only when `stage === "ready"` (Chief URL) |
| `workspace.organization_id` | Clerk Org id when bound (`org_…`), else null |
| `workspace.box_id` | Box UUID when bound, else null |
| `workspace.confirmation_available` | Whether confirm may be attempted (does not grant access) |
| `action_required` | Human-readable next step or null |

`stage === "ready"` requires entitled trial/paid billing, ready workspace, member
workspace proof, Org id, Box id, and workspace URL. Apps must not treat Org/Box
as usable for native activation until `POST /native/workspace-profile` succeeds.

### `GET /native/practices`

```json
{
  "active_practice_id": "<uuid>|null",
  "practices": [
    {
      "id": "<uuid>",
      "legal_name": "…",
      "display_name": "…",
      "role": "owner|admin|staff",
      "workspace_status": "pending|provisioning|ready|failed"
    }
  ]
}
```

### `POST /native/workspace-profile` — production handoff

Request (JSON, ≤ 4 KiB, no duplicate keys):

```json
{
  "client": "apple",
  "nonce": "<canonical UUID string>",
  "expected_revision": 12
}
```

`expected_revision` is optional; when sent it must match the current composite
revision. `client` must match `Origin` (`apple` ↔ `capacitor://localhost`,
`desktop` ↔ `app://cosmas`).

Success response (`Cache-Control: no-store`):

```json
{
  "contract_version": "cosmas-native-workspace-profile.v1",
  "client": "apple",
  "nonce": "<same UUID>",
  "native_origin": "capacitor://localhost",
  "data_mode": "authorized_beta",
  "nativeIdentity": {
    "version": 1,
    "profile": "operational-beta-v1",
    "client": "apple",
    "apiOrigin": "https://api.<practice_uuid>.workspace.cosmas.ai",
    "publishableKey": "pk_live_…",
    "frontendOrigin": "https://clerk.beta.cosmas.ai",
    "organizationId": "org_…",
    "audience": "<non-empty production audience>"
  },
  "session": {
    "issuer": "https://clerk.beta.cosmas.ai",
    "subject": "user_…",
    "session_id": "sess_…"
  },
  "practice": {
    "practice_id": "<uuid>",
    "box_id": "<uuid>"
  },
  "workspace": {
    "url": "https://<practice_uuid>.workspace.cosmas.ai/chief",
    "source_commit": "<40 hex>",
    "image_sha256": "<64 hex>",
    "workspace_proof_sha256": "<64 hex>",
    "member_proof_sha256": "<64 hex>",
    "native_qualification_sha256": "<64 hex>"
  },
  "issued_at": 1700000000,
  "expires_at": 1700000030
}
```

Field rules the client must enforce:

- Exact key set only (no extras).
- `data_mode` is `synthetic` or `authorized_beta` (never the enrollment string
  `production` on this document).
- Production (`authorized_beta`) binds `operational-beta-v1`,
  `https://clerk.beta.cosmas.ai`, non-empty `audience`, and the practice's own
  `<practice_id>.workspace.cosmas.ai` hosts.
- Synthetic binds `operational-staging-v1` and staging hosts.
- Response contains **no** bearer token and **no** email.
- Freshness window: `expires_at - issued_at` is at most 120 seconds (server
  typically issues ≤ 30 seconds). Re-fetch with a new nonce after expiry;
  expiry is not a billing gate by itself.

Shared validators:

- JS: `clients/shared/native-practice-profile.mjs`
- Types: `clients/shared/native-practice-profile.d.mts`
- Swift: `NativePracticeProfile` / `practice-uuid-production-v1` origin policy

## Error cases (native apps)

Errors return JSON:

```json
{ "detail": { "code": "enrollment_<code>", "message": "…" } }
```

Codes are prefixed with `enrollment_` unless already prefixed. Treat unknown
codes as unavailable and recover with a fresh status / sign-in.

| HTTP | Typical code | App behavior |
| --- | --- | --- |
| 401 | `invalid_identity`, `session_inactive`, `native_identity_invalid` | Clear local session; sign in again |
| 403 | `practice_required`, `agreement_required`, `billing_required`, `runtime_scope_denied`, `practice_access_denied`, `verified_email_required`, `workspace_preparation_pending` | Show status / resume enrollment; do not open workspace |
| 408 | `native_profile_interrupted` | Safe retry with new nonce |
| 409 | `revision_conflict` | Re-read status; retry with new revision / idempotency key |
| 413 | `invalid_native_profile` (too large) | Bug; do not retry same body |
| 422 | `invalid_native_identity`, `invalid_native_profile`, `enrollment_invalid_request` | Fix request shape / origin |
| 503 | `native_identity_unavailable`, `native_workspace_unqualified`, `registration_unavailable`, `identity_not_configured` | Feature closed or practice not native-qualified; keep browser path intact |

Common workspace-profile denials:

- Practice not selected / no membership → `practice_required`
- BAA missing → `agreement_required`
- Workspace not ready or member proof missing → `workspace_preparation_pending`
- Billing not fresh / not entitled → `billing_required`
- Clerk Org membership lost → `runtime_scope_denied`
- Host / image / origin not native-qualified → `native_workspace_unqualified` (503)
- Origin or client mismatch → `native_identity_invalid` / unavailable

Idempotent mutators require header `Idempotency-Key`. Reuse the same key only for
the exact same payload; a changed practice selection needs a new key.

## Intentionally out of scope

This contract does **not**:

- Enable unmanaged legacy native entry or change existing beta-only Box bootstraps
  that never call enrollment.
- Grant access from Checkout return URLs, webhook delivery, or JWT Org claims alone.
- Expose Stripe keys, Clerk secret keys, admission master secrets, or derived Box
  admission keys to the app.
- Define clinical APIs, Core/Scribe permissions, patient messaging, or F-8 queue
  payloads (those remain workspace APIs after activation).
- Allow agents to call enrollment human routes or occupy human seats.
- Perform mid-cycle seat repricing, 11+ self-serve checkout, tax calculation, or
  live Stripe catalog mutation from the app.
- Replace practice-access owner approval (`/practice-access/*`) for invited
  teammates joining an already-running Box outside enrollment.
- Authorize DNS, Azure apply, or Clerk dashboard changes by itself — those are
  operator / founder console steps.

## Implementation map

| Concern | Location |
| --- | --- |
| HTTP routes | `src/cosmas_os/enrollment/api.py` |
| Status + workspace profile | `src/cosmas_os/enrollment/service.py` |
| Native JWT verification | `src/cosmas_os/enrollment/auth.py` |
| Browser/TS status validators | `web/src/enrollment-contract.ts` |
| Shared native profile validator | `clients/shared/native-practice-profile.mjs` |
| Native enrollment UI | `web/src/NativeEnrollmentEntry.tsx` |
| Focused backend proof | `tests/enrollment/test_native_practice_profile.py` |
| Production profile proof | `web/src/native-practice-production.test.ts` |
| Swift production origin policy | `clients/apple/native-auth/.../NativePracticeProfile.swift` |

## Related PR merge order (Mac / iPhone) — agreed

**Agreed with Mac/iPhone Team 3** ([comment on #311](https://github.com/CosmaNeura/cosmaneura-os/pull/311#issuecomment-6658486488)):
**option B — close #305 and take #311 alone.**

Draft [PR #305](https://github.com/CosmaNeura/cosmaneura-os/pull/305) carried the
same production native-validator patch (shared/Swift/`NativeEnrollmentEntry`).
This contract PR (#311) includes that identical validator work **and** this
document. **#305 is superseded by #311.** Do not merge #305. Keep #311 as the
single draft for validators + account contract (still draft; do not merge until
ready).

## Change control

Bump `cosmas-native-workspace-profile.v1` only for incompatible field or
validation changes. Additive optional fields require a coordinated native release
and must keep exact-key validators failing closed until both sides agree.
Keep Stripe TEST qualification and production Clerk audience wiring as operator
gates; this document does not flip those flags.
