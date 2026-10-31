# October 31 customer onboarding implementation

The owner approved building the researched frontend/backend plan on October 31.
The canonical application remains `CosmaNeura/cosmaneura-os`; this feature is
consolidated on `codex/onboarding-integration-20261031`. The public marketing
site has its established separate owner, `CosmaNeura/cosmabot-web` (PR #7).
Neither location is a competing native app source. Legacy Cosmaneura/Core and
Scribe sources, services, identities and databases were not changed.

## Implemented customer flow

- Equal public pricing choices: Solo one human $300/month; two through ten
  humans $300 first plus $100 each additional; larger practices contact the
  existing company contact. USD monthly; office staff and owners are paid seats.
- Browser `/onboarding` and `/sign-in` enter before a practice organization
  exists. Clerk loads only after the selected enrollment API admits account
  creation. Existing native entry remains unchanged.
- Saved user/practice details, complete pinned company BAA v2.3 and immutable
  signer receipt. The owner may invite another authorized signer; ordinary
  staff invitations default to no signing authority.
- Owner team invitations reserve purchased seats. Shrinking the plan below
  existing humans/invitations is rejected. Invitees join the existing practice
  and do not create another subscription. Practice switching preserves separate
  identities, progress and data.
- Trial activation remains pending until a separately provisioned workspace is
  usable. Confirm practice account prepares actual Clerk membership, selects
  the saved Org and measures the exact human's signed workspace access. The
  owner setup reuses the previously saved names to consume an existing protected
  first-owner reservation. It cannot claim an unreserved Box or overwrite setup;
  a lost response recovers through the signed runtime status. Qualification also
  requires the actual completed practice profile and enforced enrollment admission.
- Stripe-hosted Checkout freezes the server-owned offer and original attempt;
  returns/retries recover it. Signed durable events and current provider reads
  confirm trial/payment state. Portal access handles billing recovery and
  cancellation; staff cannot create a subscription or open owner billing tools.
- Trial/paid readiness requires current membership, exact agreement, individual
  workspace proof and fresh authoritative billing. Failed-payment/expiry holds
  do not create a new free trial. Log out and account switching clear transient
  browser setup state; no credentials/cards are stored in browser storage.
- Workspace recovery has its own small account/billing screen. It resumes saved
  work only after a fresh protected identity check succeeds; an ordinary healthy
  server check cannot clear a payment or membership hold. Recovery links are
  explicit and restricted to the matching owned staging/production origins.

## Source and deployment map

`web/src/EnrollmentEntry.tsx`, `EnrollmentFlow.tsx`, `enrollment-api.ts`,
`enrollment-clerk.ts` and `enrollment-contract.ts` own the browser journey.
`src/cosmas_os/enrollment` owns its independent registry, identity verifier,
agreement, billing adapters, reconciliation and trusted workspace bridge.

Run the independent API with `uvicorn cosmas_os.enrollment.api:app`. It uses
only `ENROLLMENT_` settings and its dedicated SQLAlchemy/migration graph.
The existing clinical application is not its account/payment database.

`infra/enrollment/README.md` describes versioned Key Vault references, exact
Clerk identity/default session policy, immutable image/source configuration,
separate Azure state/runtime and controlled per-practice provisioning. The
renderer produces browser flags `VITE_ENROLLMENT_ENABLED=true` and
`VITE_ENROLLMENT_API_BASE=<enrollment-api-origin>`; it cannot grant readiness.

`tests/enrollment` proves identity, authority, prices, receipt immutability,
durable retry, failed/out-of-order billing, capacity and proof boundaries.
`web/src/EnrollmentServerJourney.test.tsx` drives real DOM controls against the
actual loopback synthetic API. CI includes those journeys and a separate
PostgreSQL enrollment database. Existing CI, Trivy and main protections remain.

## Verified scope and remaining activation gates

Focused backend/browser checks and actual synthetic HTTP owner/staff journeys
passed. The signed runtime qualification path was checked on a temporary owned
PostgreSQL database. Ruff/Pyright and the browser build passed; OpenTofu runtime
validation passed without a plan or apply. The copied BAA's exact SHA-256 is
verified inside the built package. These checks use invented identities and
fake external providers; they do not prove live Google/Microsoft/password or
Stripe cancellation/reminder delivery.

Before hosted staging/production activation, complete actual Clerk method and
workspace session-policy compatibility, own Stripe catalog/portal/webhook and
test-clock cancellation/reminders, dedicated durable Azure database/runtime,
actual per-Box owner/team provisioning, backup/restore and release qualification.
The deployer must verify Azure's actual image digest, not infer it from runtime
environment metadata. Tax, seat changes, cancellation/export/retention and
account/service privacy terms still need the final commercial release policy.

Production follows the successful staged customer journey, as requested.
Production registration/marketing trial acquisition remain closed by default.
No production infrastructure, live Clerk/Stripe settings, domain routing or
mail settings were changed by this implementation milestone.
