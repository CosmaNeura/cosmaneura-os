# CosmaBot Stripe TEST setup and qualification

Prepared from `e0d522bf8329e0a6b05ea36fff435092d2f505a2` and the approved
October 31 onboarding plan. This is an operator procedure; no Stripe objects,
credentials, messages or deployments were created by preparing it. Bind the
eventual staging receipt to the exact built commit, including card-only Checkout.

## 1. Prepare the selected test environment

Use a dedicated CosmaBot Stripe sandbox under the selected merchant account.
This isolates catalog, webhook delivery and reminder settings from existing
Cosmaneura subscriptions. If using the merchant's existing test mode instead,
first inventory the effect of shared settings and its unrelated event traffic;
the current inbox retries unbound supported events. Use only synthetic practice
information and the operator's own test login. Never use a live key or real card.

Keep credentials in the approved protected store. The reference worksheet is
[`infra/enrollment/stripe-test.reference.json`](../infra/enrollment/stripe-test.reference.json);
it contains empty public IDs and secret-reference slots, and is deliberately
not accepted as a deployment manifest. Fill a protected copy, then transfer its
four public IDs and exact versioned Key Vault references into the existing
version-1 enrollment manifest. Preserve separate enrollment DB, Clerk and
runtime-admission references. Do not print API responses containing secrets.

| Operator action, TEST API v1 | Required configuration |
| --- | --- |
| `POST /v1/products`, then `POST /v1/prices` | CosmaBot first-human product; `currency=usd`, `unit_amount=30000`, `billing_scheme=per_unit`, recurring `interval=month`, `interval_count=1`, `usage_type=licensed`, active |
| `POST /v1/products`, then `POST /v1/prices` | CosmaBot additional-human product; same fields, `unit_amount=10000`, a distinct active price ID |
| `POST /v1/billing_portal/configurations` | Dedicated active TEST configuration: invoice history and payment-method update enabled; cancellation enabled at period end; subscription/quantity/plan edits and customer edits disabled; public portal login disabled; no retention coupon or proration |
| `POST /v1/webhook_endpoints` | Exact selected enrollment API origin + `/enrollment/v1/webhooks/stripe`; account endpoint, not Connect; explicitly pin endpoint `api_version=2025-09-30.clover`; enable only the events below |

Use `Stripe-Version: 2025-09-30.clover` for setup/inspection calls. Store the
new endpoint signing secret directly in the enrollment TEST secret store;
the Stripe CLI forwarder's secret is a different credential. Do not rotate an
existing product's endpoint or alter account-wide payment settings.

Subscribe the enrollment endpoint to this exact supported set:

```text
checkout.session.completed
checkout.session.expired
customer.subscription.created
customer.subscription.updated
customer.subscription.deleted
customer.subscription.paused
customer.subscription.resumed
invoice.paid
invoice.payment_succeeded
invoice.payment_failed
```

The runtime key needs the corresponding permissions for these calls only:
`GET /v1/account`, `GET /v1/prices/{id}`,
`GET /v1/billing_portal/configurations/{id}`,
`POST /v1/checkout/sessions`, `GET /v1/checkout/sessions/{id}`,
`GET /v1/subscriptions/{id}`, `GET /v1/invoices/{id}` and
`POST /v1/billing_portal/sessions`. Exercise each with the selected restricted
TEST key; Stripe permission categories can bundle dependencies. Catalog,
webhook and portal-configuration creation are operator permissions, not runtime
permissions. Webhook reception authenticates its signature, not that API key.

## 2. Admit only the prepared staging journey

Set TEST mode (`ENROLLMENT_STRIPE_LIVE_MODE=false`) and pin the account, two
prices, portal ID, API version and two Stripe secret references. The renderer
uses `ENROLLMENT_DATA_MODE=synthetic` for staging; run the real enrollment API
entrypoint, not the loopback lab/fake-provider entrypoint. Restart the API after
changing the catalog/configuration: its public billing admission includes a
startup catalog check. Confirm `/enrollment/v1/config.billing_configured=true`;
`/ready` returning 200 alone proves only registration admission.

Enable the staged trial only after the independent DB,
Clerk methods, exact BAA, provisioned Box, owner initial setup and actual scoped
workspace confirmation are qualified. The existing deployment manifest requires
the reviewed journey receipt and readiness flags. `activation_available` also
requires the real workspace confirmer. Before those gates, show saved progress
and activation pending: no Checkout, subscription or trial clock.

Every human consumes a purchased seat, including owner/admin/staff and pending
invites; paused humans retain a seat until explicitly removed. Agents consume
none. Total monthly USD is `300 + 100 * (humans - 1)`: 1 = $300, 2 = $400,
5 = $700, 10 = $1,200. Eleven or more cannot open Checkout. Mid-cycle seat
changes and portal plan/quantity changes are unavailable. The current offer
adds no tax, discounts, fees or add-ons; approve that treatment and cancellation
and notification terms before `commercial_terms_verified`.

## 3. Run the bound owner/staff test journey

Use the actual staging frontend and its configured enrollment API. Requests use
a fresh default Clerk bearer token and
`X-Cosmas-Enrollment-Contract: enrollment.v1`. Each mutation needs a fresh
`Idempotency-Key` plus `{ "expected_revision": <latest saved revision> }`;
retry the same operation with the same key/body after a lost response. Prices,
customer IDs, workspace destinations and trial dates never come from the client.

| Case | Action and acceptance evidence |
| --- | --- |
| Account to readiness | Owner account → practice → exact v2.3 BAA/immutable receipt → actual owner setup/confirmation. Attempt `POST /enrollment/v1/checkout` while pending: denied, no provider object and no trial start. |
| Correct price/card | At ready, inspect `GET /enrollment/v1/quote`, then `POST /enrollment/v1/checkout`. Hosted TEST Checkout requires a card, base quantity 1 plus extra quantity `humans-1`, zero due today, monthly USD total above, exactly 14 trial days, no added charge items. Use Stripe's documented TEST cards, never a real card. |
| Canceled or lost Checkout | Follow its cancel return before payment, reload and `POST /enrollment/v1/recover`. Same stored open session/attempt, no subscription/trial/access. Repeated `/checkout` recovers it; provider-confirmed expiry without a subscription permits a fresh attempt. An uncertain old attempt requires operator reconciliation, not another subscription. |
| Successful activation | Complete hosted Checkout; recover/reconcile the saved session and subscription. Save exact IDs and UTC trial start/end; difference is `1,209,600` seconds. Redirect alone grants nothing. Owner and qualified invited staff use the same practice subscription and each pass the real runtime `/account/identity` gate. |
| Portal/card update | Owner `POST /enrollment/v1/portal`; server chooses the stored customer, pinned portal and return origin. Invoice history/card update/cancellation work; no plan or seat editing. Card update preserves the saved trial start/end and creates no early nonzero invoice. Staff cannot open owner billing operations. |
| Trial cancellation | Cancel in that portal before trial end. Recover and inspect canonical `cancel_at_period_end=true`; display the saved end date and cancellation. No second trial. Confirm in the clock cohort below that this exact policy cancels at trial end without the first nonzero charge. |
| Delivery/recovery | Stripe resend of a bound event keeps the same event ID with a fresh signature. Delay/reorder deliveries, restart API/worker, run the private sweep and recover. One subscription, durable dedup, unchanged trial, no false readiness. A malformed/stale signature, wrong mode/account/version or forged return cannot grant access. |
| Failed payment/access | Use the provider cohort for timed failures; on a bound staging subscription, a legitimate failure/cancellation must pause bookmarked workspace access and queued clinical work. Updating a card alone does not clear a failed-invoice hold: the exact failed invoice must become authoritatively paid before a fresh runtime request succeeds. |

The private scheduler runs every minute with the enrollment DB and TEST key:

```sh
python -m cosmas_os.enrollment.reconcile
```

HTTP 200 from the webhook acknowledges durable receipt, not a completed
entitlement transition. Inspect reconciliation/status and the actual runtime
gate. Generic `stripe trigger` objects are not bound to a registered practice.
Do not log bearer tokens, card details, customer emails or complete provider
payloads in the receipt; keep public IDs, hashes, prices, UTC dates and outcomes.

## 4. Qualify provider timing with separate test clocks

The current enrollment API has no test-clock/customer override: a new Checkout
creates its own customer. The access policy also uses real UTC, not Stripe's
virtual clock. Do not shorten a saved trial or attach a simulated customer by
editing the registry. Provider clock results qualify billing policy, not the
registered practice's timed runtime-access transition.

In a separate disposable TEST sandbox, recreate the identical catalog/portal
policy and use an observation endpoint that does not target enrollment. Create a clock with
`POST /v1/test_helpers/test_clocks`, then a **new** customer with its `test_clock`,
and a subscription using the corresponding two prices/quantities and `trial_period_days=14`.
Use only Stripe TEST payment methods. Create separate canceled, successful-paid
and failed-payment cohorts. Give these provider-only objects no enrollment
contract/practice metadata. A second endpoint in the enrollment sandbox would
not isolate its events: account endpoints receive all subscribed event types.

Advance `POST /v1/test_helpers/test_clocks/{id}/advance` to just before trial
end, then beyond it; wait until the clock is ready after each advance. Check:
trial invoice zero; cancellation at period end yields canceled with no first
nonzero paid charge; uncanceled successful card bills the exact monthly total;
failed/authentication-required TEST method does not become paid; paying the
same invoice recovers it; card change never resets the trial. Retain sanitized
event IDs/statuses. Delete only this disposable cohort after retaining evidence.

Do not count a Dashboard subscription simulation as the bound registration
journey. End-to-end fourteen-day expiry still needs a real-time staged cohort
or a separately reviewed private clock-aware harness; neither is implemented by
this worksheet. `customer.subscription.trial_will_end` is not handled by the
current inbox and there is no owned reminder sender. Qualify the selected
Stripe-managed reminder/cancellation link and actual delivery to the operator's
own account separately before declaring notification readiness. Preparing this
procedure sends no email and changes no shared reminder settings.

References: [Checkout API](https://docs.stripe.com/api/checkout/sessions/create?api-version=2025-09-30.clover),
[portal controls](https://docs.stripe.com/customer-management/configure-portal),
[webhook endpoint API](https://docs.stripe.com/api/webhook_endpoints/create?api-version=2025-09-30.clover),
[test-clock API](https://docs.stripe.com/billing/testing/test-clocks/api-advanced-usage),
[trial compliance](https://docs.stripe.com/billing/subscriptions/trials/manage-trial-compliance).
