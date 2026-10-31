# Private enrollment clock source qualification

This harness is source evidence for M3. It does not qualify hosted Stripe or
grant staging/production readiness. Its receipt always reports
`hosted_stripe_runtime_qualified: false`.

Run from a complete local source checkout with the normal development Python
dependencies and PostgreSQL tools available:

```sh
python scripts/qualify-enrollment-clock.py --receipt /private/tmp/enrollment-clock-receipt.json
```

Use a fresh source checkout without an application `.env`, and a fresh owned
private receipt path. The runner strips inherited application/enrollment settings
and binds every application database reference to its own local runtime. It creates and removes its own
loopback PostgreSQL server, central `enrollment_synthetic` database and separate
`enrollment_runtime_synthetic` database. It refuses success when any case fails,
skips, or does not finish within its local process bound. The receipt is created
0600 and contains test names/results only. The CLI accepts no credentials,
customer IDs, clock IDs, dates, card data or live mode. It makes no vendor calls.

## What runs

`tests/enrollment/clock_harness.py` privately composes `StripeCommerce` with an
invented HTTP provider transport. The production adapter validates the merchant,
prices, portal configuration, frozen Checkout request, signed webhook and
canonical subscription/invoice reads. The private composition creates its own
synthetic clock/customer and binds one practice to that customer. Enrollment
HTTP clients cannot select a customer, clock or date. The original provider
trial tuple is immutable; advancing targets derives only from its exact original
14-day period. An unready clock or changed customer/clock binding withdraws the
virtual-time snapshot.

The period-time port affects only trial/paid-period eligibility and period-end
refresh triggers. Default deployed enrollment still uses real UTC. A custom
period port is rejected in production mode. BAA/command timestamps, invitation
expiry, provider-read freshness, Clerk JWT/session checks, signed request age,
nonces and signed response timestamps remain on real wall time. Admission TTL
is capped by the remaining business period translated to wall time and by the
existing physical freshness/security limits. No production clock environment
setting or clock/customer/date HTTP override was added.

The four persisted runtime cases perform actual owner reservation/setup and
signed qualification before Checkout. They use the existing managed workspace
API and signed central admission adapter, with invented Clerk identity and an
invented Stripe transport:

- At trial end minus one second, the runtime admits the registered owner and
  worker-purpose request with a wall-time proof lifetime at most one second.
  At exact expiry and expiry plus one second, a provider still reporting
  `trialing` cannot grant workspace or worker access. The original UTC duration
  remains exactly 14 × 86,400 seconds, including across daylight-saving changes.
- Cancellation before expiry preserves access through the original period;
  expiry/deletion denies bookmarked runtime calls. The synthetic provider emits
  no first invoice/charge and duplicate recovery creates no subscription/trial.
- Failed first payment and provider outage deny runtime access. Canonical paid
  proof for the same invoice restores access through recovery. Duplicate old
  failure delivery/recovery preserves the original subscription and trial and
  produces one synthetic successful charge.

Four additional checks reject production injection, unready/rebound clocks,
changed original trial dates and HTTP customer/date override; preserve physical
billing freshness; and reject expired real JWTs/old signed requests even when
the business period is advanced almost fourteen days.

Two recovery checks retain the last qualified clock timestamp across an unready
response or provider read failure. Admission loses its usable time snapshot
while the provider is unavailable; recovery rejects a timestamp older than the
last qualified value and permits an equal or later value.

## Remaining hosted M3 gate

The invented transport accepts a clock-bound customer in hosted Checkout. This
has not been verified against Stripe TEST. If Stripe rejects that combination,
an API-created subscription is not a faithful replacement for this customer
Checkout journey and cannot close M3.

A faithful hosted run still needs protected TEST credentials and a separately
qualified private synthetic composition that binds an actual TEST clock/customer
before Checkout. Its registered runtime must call that composition's actual
owned HTTPS admission service while the service reads the bound ready provider
clock for period eligibility. The ordinary deployed enrollment API uses wall
time, so advancing a provider clock against it cannot prove runtime expiry.
Private composition must retain the actual Clerk verifier, current registered
member checks, immutable Box/Org binding, per-Box derived signature key and
existing setup/provisioning proof. Actual clock readiness/advance behavior,
Checkout compatibility and same-invoice provider evidence must be verified;
this source harness supplies no replacement readiness flags.

The source runner intentionally has no hosted/live execution switch. Actual
Stripe cancellation/no first charge, card failure/payment recovery, reminders,
TLS/runtime behavior and delivery still require that protected qualification.
