# Staging onboarding delivery

This milestone prepares a separate CosmaBot account service and two isolated
synthetic practice workspaces. Production acquisition, charging, infrastructure
and activation remain on hold until the hosted acceptance journey passes.
Cosmaneura/Core/Scribe services, identities, databases and source are unchanged.

## Customer journey and commercial contract

The account-only site collects the human's profile and practice details, saves
progress, presents the existing Cosmaneura BAA v2.3, confirms the workspace is
usable, and then sends the owner to card-only Stripe Checkout. A successful
return URL alone never grants access. Canonical provider evidence and the
registered workspace's signed admission contract determine access.

The offer is USD monthly: $300 for the first human, $100 for each additional
human through ten, and negotiated pricing above ten. Owners, providers, office
staff and administrators each occupy a paid seat. Pending invitations reserve
seats; paused members retain seats. Seat changes and proration remain closed.
The original trial is exactly 14 usable UTC days and cannot be restarted by
duplicate requests, webhook delivery or billing recovery.

The central account hostname is `onboarding.staging.cosmas.ai`; its API is
`enrollment-api.staging.cosmas.ai`. Account-only builds route every unmatched
URL back to account setup and cannot fall through into a workspace. Existing
workspace/native build profiles keep their existing behavior.

## Deployment order

1. Qualify the existing CosmaBot Clerk development instance's password,
   Google and Microsoft sign-in, authorized account origin and organization
   binding. Keep its existing beta production instance untouched.
2. Qualify the separate Stripe TEST catalog, card-only Checkout, immutable
   pricing and 14-day trial, portal restrictions, webhook signatures and
   canonical reconciliation. Use protected references rather than key values
   in source or logs.
3. Prepare, review and apply only the isolated staging foundation described in
   `infra/enrollment/foundation/README.md`. Retain the encrypted state and its
   protected recovery key separately. Review cost/capacity before apply.
   Central US is the measured staging default: the subscription's October 31
   catalog rejects new PostgreSQL in East US 2 and East US, while Central US
   lists PostgreSQL 16/B1ms/32 GiB and Container Apps. Catalog support is not an
   allocation guarantee. East US 2 remains a bounded source option that needs
   a new capacity check; regions outside these two are rejected.
4. Run the private database bootstrap job and verify the restricted application
   role. Build and push images from the accepted source; use registry manifest
   digests, not local Docker configuration IDs.
5. Prepare two saved synthetic practices using
   `infra/enrollment/workspaces/README.md`. Perform owner reservation, migration,
   signed owner setup and qualification before registering either workspace as
   ready or opening Checkout. Give each Box only its derived admission key and
   own storage/database access.
6. Deploy the central account/API containers with acquisition closed. Verify
   CNAME/asuid records against both documented resolvers, bind managed TLS and
   run the deployed-host verifier from `infra/enrollment/STAGING-HOSTING.md`.
7. Complete the hosted acceptance gates below, then enable staging enrollment.
   Publish the companion marketing change only after its link reaches this
   verified journey. Production requires a subsequent deployment decision.

`/operational-ready` checks the owned schema while enrollment is closed; it is
only a container readiness probe. `/ready` and customer admission retain their
separate configuration, provisioning and billing gates. Neither a successful
probe nor a Terraform mock plan grants customer access.

## Acceptance evidence

Source checks cover account-host routing, restricted database roles, exact
two-practice origin/Box/Org bindings, real loopback signed owner setup, unfinished
Checkout denial, wrong-owner denial and cancellation/recovery. Mock plans cover
private network and per-secret identity wiring without cloud changes.

The private clock runner in `docs/ENROLLMENT_CLOCK_QUALIFICATION.md` exercises
actual persisted runtime admission across expiry and failed-payment recovery
with an invented provider transport. The deployed default remains real UTC;
JWT, nonce, signature and provider-read freshness always use wall time.
This evidence does **not** qualify actual Stripe TEST or hosted runtime expiry.

Hosted acceptance still requires:

- Real Clerk password and both OAuth paths, sign-out/re-entry, saved progress,
  correct practice selection, and denial across the two practice boundaries.
- Exact BAA acceptance evidence and card Checkout for one, two and ten humans;
  more than ten leads to contact rather than an unapproved subscription.
- Abandoned signup/Checkout, duplicate delivery, outage and recovery without a
  new trial, duplicate subscription or premature charge.
- A faithful Stripe TEST clock/customer-bound Checkout and the registered
  runtime calling its separately qualified private HTTPS clock composition;
  provider-only clock advances against a wall-time service do not close expiry.
- Original trial end minus one second, exact expiry and plus one second;
  cancellation before first charge; failed first payment and same-invoice
  recovery; actual reminder delivery.
- TLS, production-style image ownership, encrypted recovery custody, rollback
  to closed acquisition and the complete synthetic owner-to-Chief journey.

If access or a provider is unavailable, preserve the existing subscription and
practice records, hold admission, and reconcile authoritative evidence. Do not
replace the journey with manually granted entitlement or a shorter trial.
