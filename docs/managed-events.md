# Managed status-event routes

Supply `ManagedEventProfile` through the existing `ManagedServiceProfile.events`
before ordinary API startup. Each delivery `EventRoute` or `FinanceEventRoute`
must include `expected_selection`, the exact existing native account version.
Configuration must match one installation in the supplied catalog. An installation
identifier cannot stand for a reviewed account version. Delivery routing also
matches the installed `event_route_id`; duplicate routes and ambiguous accounts
are rejected before startup opens any resources or changes any account.

Lookup is an in-memory operation. The ordinary receiver checks the selected
database account, owner, Box, environment and private selection commitment before
verifying the raw request signature and retaining a candidate. Spruce and Stripe
use their existing signature verification. SRFax and Documo callback payloads
remain untrusted hints. Secrets and private account selectors are never returned
to the renderer or callback sender.

Event gates remain separate from work/submission gates. Disabling submissions,
disabling an account or revoking a human login does not erase properly bound late
evidence. Disabling the event gate or stopping the runtime refuses new callbacks.
Duplicate callbacks retain one candidate. Callbacks do not submit, retry or mark
work complete; existing explicit reconciliation/review determines final outcomes.

Keep explicit historical bindings for late callbacks during account rotation.
Each configured callback URL identifies one native version. A new binding with a
different version cannot silently replace an existing route; publish a distinct
reviewed route/configuration and retain the historical route while needed. This
module performs no webhook registration, account onboarding or external network
activity at startup. Host configuration and real vendor acceptance remain separate.
