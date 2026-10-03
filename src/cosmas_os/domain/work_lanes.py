"""Private connector work is exposed only through its scoped review surface."""

PRIVATE_CONNECTOR_LANES = frozenset({
    "account_efax_inbound",
    "encounter_vendor_delivery",
    "encounter_payment_request",
    "encounter_portal_work",
    "encounter_membership_work",
    "encounter_inbox_handoff",
})
