# Private Stripe TEST clock composition

`cosmas_os.enrollment.private_clock_lab` is an explicit private ASGI factory for
M3 qualification. The ordinary API, settings, Stripe adapter and service remain
unchanged. There is no production clock flag, public clock/date/customer route,
or hosted qualification claim. Development Clerk and Stripe TEST are mandatory.

Start with one practice already saved through the normal enrollment API: profile,
legal practice and immutable v2.3 BAA, followed by the protected provisioner's
reserved Box/Org and measured release/destinations. The private binding freezes
that practice, its owner, issuer, canonical UUID5 Box, Org, account/API origins,
workspace origins/release, merchant/catalog, TEST customer/clock, initial provider
time, and the separate private journal's host/port/database. Credentials never
enter the binding. The customer must belong to that ready clock and have no
subscription when the operator prepares it.

Use `prepare_clock_binding(settings, registry_engine, protected_manifest,
binding_path=..., journal_engine=...)` from a protected operator process. Settings
come from protected credential custody, never command-line values. Its provider
and Clerk operations are canonical GETs; it creates no vendor object. It writes
the reference-only binding to a fresh owner-only 0600 file under an owner-only
0700 directory. It prepares only `private_stripe_clock_journal` in the distinct
database `cosmabot_enrollment_clock_lab`. Its SQLAlchemy metadata is independent
of enrollment and clinical migrations. It refuses another database, host/port
binding or remote connection without `sslmode=verify-full`.

Host with explicit `create_clock_lab_app(settings, engine=registry_engine,
binding_path=..., journal=PostgresClockJournal(journal_engine, binding))`. No file
journal or memory journal is accepted. The journal must already exist; normal
startup never creates or resets it. Preparation DDL belongs to a separate operator
identity; the private app needs only the selected journal row's SELECT/UPDATE.
Do not reuse production/clinical grants or grant DDL to the app. No infrastructure
or SQL-role change is included here. Lost preparation responses recover from the
same binding and existing row, rather than another preparation or customer.

Each accepted period read refreshes the canonical ready clock and its customer
association. An unready clock, outage, binding collision or rewind denies access.
PostgreSQL row locks commit the qualified high-water, pending advance and first
canonical subscription/trial tuple atomically across processes. Restart retains
those records. The production subscription validator still requires its original
14 × 86,400-second trial, exact human-seat prices and stored Checkout attempt.
It validates a rollback-only snapshot here; normal EnrollmentService remains the
only writer of canonical billing evidence and its physical read timestamp.

The private trusted operator method `commerce.advance("before"|"expiry"|"after")`
derives its target exclusively from that original trial end: −1, 0 or +1 second.
It durably records the target before a TEST-clock POST and uses a stable provider
idempotency key. Interrupted/async advances remain pending and cannot reuse an
old period snapshot. Repeat the same point, or poll through normal saved-status
recovery, until the bound clock is ready at the same target. It never accepts a
customer, clock ID or arbitrary date. These are future protected operator writes;
the source tests make no vendor calls.

Only the bound owner and Org reach the existing enrollment/recovery/setup paths.
Other practice creation/join/invitation paths are closed in this composition.
Signed runtime and worker requests must match the immutable bound practice,
Box/Org/issuer/owner before any period read. The real Clerk verifier still checks
JWT/session/user/current Org membership; worker admission still supplies no
human approval. Signed Stripe events must belong to the bound customer and saved
attempt/subscription. Event ingestion can remain durable while a clock advances,
and preserves the production signature and billing-cache invalidation rules.
JWTs, webhook signatures, HMAC age/nonces, response TTLs, BAA/command dates and
canonical billing-read freshness remain on wall time.

For hosted M3, deploy this explicit factory behind a separately owned private
HTTPS admission origin, with actual durable journal credentials/custody. The
registered practice must use that exact origin and its own derived admission key;
the global master and Clerk backend key stay central. Keep existing staging and
production unchanged. The current Azure runtime has no persistent file volume;
this module does not infer one. Actual private SQL roles/connectivity, journal
restart/restore, HTTPS/runtime/setup measurement, Stripe clock readiness and
before/at/after expiry, cancellation/no first charge and same-invoice recovery
must still be qualified. Accepted TEST customer→Checkout capability alone does
not pass the registered-runtime timing gate.

Focused source tests use invented provider HTTP, the actual Clerk verifier,
production billing/admission and an always-owned loopback PostgreSQL journal:

```sh
python -m pytest tests/enrollment/test_private_clock_lab.py -q
```

These tests are source qualification. They do not report hosted M3 readiness.
