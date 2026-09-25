# Core location deadline integration

This is an isolated derivative of the root-owned connected-record location
route. It adds no clinical record store, capture/note/model action, migration or
authority. The existing three calls remain context exchange, interaction
resolution and binding resolution. They can create their existing Core metadata
records; timeout does not assert that an already dispatched call was undone.

## Wiring

Apply the three product modules and three unit-test files in this overlay. In the
existing `app.py` router registration, replace `get_session=get_session` with
`session_factory=SessionLocal` and remove
`capture_connection=_capture_connection`. The new default `record_connection`
factory creates the bounded location-only client in the worker. A context-manager
factory can instead be passed explicitly as `connection_factory=settings_budget_factory`
for a separately reviewed synthetic integration. It must create fresh owned
resources inside the worker; never return a request-owned/shared client.

Keep `identity_dependency=_identity` and `workspace_gate=_workspace_gate`. The
same functions now run in the worker under its deadline and Session. Other
capture routes retain their current `_capture_connection` and Session dependencies.
`ROOT_WIRING.patch` shows the exact one-call change against the preserved app
preimage. No app/configuration/runtime file is part of this product overlay.

Prior integration tests that override the request `_capture_connection`
dependency do not override this factory. Update the location test composition to
pass its fresh synthetic worker factory. It must preserve the same signed
identity, current patient/workspace/account checks and exact Core binding values.

## Lifetime and transport

The fixed route begins one 30-second monotonic deadline before body, workspace
gate and signed identity verification. It buffers at most 4 KiB of public output.
The worker runs in a fresh Context, acquires its own Session and closes its own
Core client/credential. Timeout or disconnect sets a cancellation fence and
signals any active worker HTTP task; the request never closes the worker's
resources from another thread. A late identity, token or response cannot start
the next Core phase. A late output header cannot admit the private location body.
Partial output is a failed read, never a second status appended to the body.

On failure the work fence is cancelled immediately. Every static error response,
including a 504 after work expiry, has one additional **250 ms maximum transport
grace** for the entire error send. A stalled error header/body cannot keep the
route open indefinitely. This grace conveys only the small error code, does not
authorize any private body/work, and never renews the 30-second work budget.

The existing workspace application still reauthorizes between every Core call.
The worker also rechecks current authority and destination before disclosure.
Each source SQL statement receives the remaining statement limit and at most a
two-second lock limit. New statements and commits refuse after cancellation;
pending ORM writes/flushes are disallowed for this location operation. SQL hooks
are local to that worker Session/its transaction Connections and are removed
before the worker's final rollback/close.

The additive client reuses existing Core payloads and receipt validators, but
allows only the three exact Core POST paths. It uses the qualified custody
transport pattern: an owned asynchronous request under the aggregate deadline
inside the synchronous worker. The selected managed identity uses the same
bounded public Azure SDK transport. There are no SDK/HTTP retries, redirects or
ambient proxies. The configured identity/scope and Core origin remain unchanged;
the scope is captured so mutable configuration cannot change it mid-request.
Response bodies and headers are separately capped at 16 KiB, raw encoded bodies
are rejected, and identity error bodies do not enter provider error messages.
The SDK selects its normal managed-identity endpoint; no alternate credential
chain or application-supplied token URL is added.

These deadlines bound admission and public response handling. Already-admitted
network bytes may arrive later. A system DNS call, pool health/connection
initialization or resource cleanup can finish privately after cancellation;
subsequent source SQL/Core work must refuse. Shared Clerk verifier refresh
remains existing independent authentication infrastructure, not a new request
operation. The overlay does not claim to cancel or undo remote metadata writes.

## Evidence and remaining acceptance

Offline qualification denies operating-system network access and Python socket,
DNS, PostgreSQL and SQLite connections. It exercises actual ASGI routing,
the existing application three-phase chain and inherited validators against
invented in-process HTTP responses, plus the installed managed-identity SDK
against its bounded injected transport. Session/SQL hook checks use doubles.
The baseline slow-identity regression failed before the fix. Initial missing
fixture/import diagnostics and later fixture bearer correction remain preserved.

This is not PostgreSQL lock, real TCP cancellation, actual Core human-session,
device or service acceptance. Root must compose the exact wiring and run the
separately reviewed fresh local SQL/TCP packet, then browser/device work within
its existing authority. Native launches, original Track A writes, external
activation, deployment and release remain outside this offline overlay.
