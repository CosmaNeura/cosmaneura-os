# Fax account activation — current implementation, October 3, 2026

This is a code inspection of the existing adapters and qualification fixtures,
not a new vendor certification or proof that any live account is connected.
No credentials, fax image downloads, real recipients or live deliveries were used.

| Provider | Account setup represented in CosmaBot | Remaining operational acceptance |
| --- | --- | --- |
| Spruce | Host-installed production selection, protected bearer credential, reviewed `internal_endpoint_id`, separately reviewed upload and fax operation, and signed callback composition. | Obtain the account's enabled API access and fax endpoint; configure and verify callbacks so the asynchronous send request can be associated with the posted conversation item. An API posting receipt does not establish fax transport delivery in this adapter. Retain explicit human verification in the provider system. |
| SRFax | Host-installed production selection with positive numeric account/access ID, protected access password, reviewed caller ID **and sender email**, reviewed PDF/recipient, exact approval. | Activate the actual account, verify routing and credentials, then qualify one controlled submission and its matching `Get_FaxStatus` read. Provider queue acceptance and final transport status remain separate. A missing queue reply must not trigger another send. |
| Documo | Host-installed account UUID and environment-specific selection, protected Basic credential, reviewed caller ID, exact PDF/recipient approval. Existing qualification records require a key that can read status as well as submit. | Confirm account/key permissions for both submission and status reads, select the intended sandbox or production installation, and qualify the same message ID, outbound direction, account and destination through delivery status. A send-only key cannot establish working follow-through. |
| eFax Corporate | Existing outbound account selection plus a separate reviewed inbound installation/grant; protected current bearer credential; exact action approval before submission or image acquisition. | Obtain appropriate API account access and protect coordinated token renewal. Validate outbound status and controlled receive independently. Inbound metadata, acquiring an image and releasing human-reviewed text to Chief are distinct steps. |

The host must provide a pinned installation manifest (or explicit managed service
profile), current protected credentials and private artifact storage. Configuration
alone does not activate the owner's account, enable external I/O, prove credential
health, approve a recipient, or authorize an action. An ordinary user should see
**Setup needed** until these steps are complete; **Verified** should require a
recorded successful check within its stated scope.

Current asymmetry: the received-fax custody, preview and Chief handoff path is
implemented for eFax. The Spruce, SRFax and Documo adapters inspected here implement
outbound submission and follow-through; they do not automatically inherit eFax's
inbound acquisition path. Adding those receive adapters is separate work.

Code evidence: `application/vendor_settings.py`, `application/fax_status.py`,
`adapters/vendor_connectors/{transport,spruce,srfax,documo,efax}.py`,
`ports/vendor_connectors.py`, `lab/provider-lessons/{spruce,srfax,documo}.json`,
and `docs/managed-services.md`. Consult the reviewed vendor references before
implementing any endpoint or entitlement change; this document does not invent
provider capabilities.
