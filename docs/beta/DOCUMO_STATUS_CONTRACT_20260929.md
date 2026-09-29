# Documo delivery-status reconciliation

The v1 adapter previously treated every failed fax as an unknown result. An
authenticated fax-info response with `status: failed` and a documented failure
code now records `transport_failed`, which the existing delivery workflow maps
to `failed`. Partial-page counts remain attached to the observation. This does
not infer that nothing was transmitted and does not resend the fax.

Contract checked against [Documo's official v1 documentation](https://docs.documo.com/)
on September 29, 2026:

- [Fax info](https://docs.documo.com/#c2dc1026-15d7-42ae-ac90-05c3757635f8)
  is authenticated `GET /v1/fax/:messageId/info`.
- [Result codes](https://docs.documo.com/#result-codes) distinguish `0` (OK),
  `1000` (pending), and the documented failure codes from `4000` to `9000`.
  The adapter uses the listed values, not the entire numeric range.
- The fax-history contract lists `failed`, `success` and `processing` statuses;
  outbound extended callbacks can also describe `transmitting`.

Unknown, missing, non-string or contradictory failure codes remain `unknown`.
Existing exact message/account/direction/destination checks and strict page
counts still apply. Callbacks remain untrusted hints requiring an authenticated
read. Raw provider details are not projected to the workspace.

Local tests use invented responses. A Documo account has not been activated or
tested by this change. The provider sandbox documents that it sends no real
faxes; sandbox acceptance and a separately approved real synthetic delivery are
distinct remaining checkpoints.
