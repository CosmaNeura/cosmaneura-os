# Connections: usability and activation

The owner wants every connection group advanced. Google/Gmail and
Microsoft/Outlook are the first activation milestone, followed by Scheduling,
messaging/fax, payments and supported patient portals. This change improves
the shared web/Mac/iPhone interface; it does not activate vendor accounts.

## Delivered behavior

- The landing page has equal square **Connect your practice** and **Choose an
  encounter** cards, with an 18px gap. They stack with a 14px gap on small phones.
- Connections are grouped by practice, email/calendar and practice services.
  The signed, read-only `/connections/catalog` reports setup availability from
  server configuration and required OAuth runtimes. It returns no account data.
- **Available** means setup can be opened, not that an account is connected.
  **Setup needed** opens instructions instead of mounting an unavailable editor.
  Failed availability reads say **Review setup**, retain existing editors and
  allow retry. Each service still enforces its own authentication and permissions.
- Gmail and Microsoft show matching sign-in steps, access explanations and
  primary connection buttons. Existing PKCE, encrypted token custody, native
  authorization handoff, account checks and disconnect behavior are retained.

The retained staging configuration has Core enabled and Google/Microsoft,
Scheduling and managed-service setup disabled. The installed Mac build also
reports Google unavailable and lacks its native OAuth configuration. Thus a UI
build alone does not complete a real Gmail or Outlook connection.

## Reuse assessment

| Resource | Verified license / use | Decision |
| --- | --- | --- |
| [Activepieces](https://github.com/activepieces/activepieces) | Community code MIT; enterprise paths excluded | Continue the existing attributed Google/Microsoft OAuth and read patterns. These are already implemented here. |
| [Google API Python client](https://github.com/googleapis/google-api-python-client) | Apache 2.0 | Official SDK option for future Google features; not needed to replace the existing narrow HTTP adapter. |
| [MSAL Python](https://github.com/AzureAD/microsoft-authentication-library-for-python) | MIT | Official Microsoft auth reference; preserve current tenant and custody boundaries. |
| [Nango](https://github.com/NangoHQ/nango) | Elastic License 2.0 | Useful embedded connection UI and token management reference; not an unrestricted MIT component to adopt without license/product review. |
| [Pipedream](https://github.com/PipedreamHQ/pipedream) | Custom Source Available License | Catalog/design reference; not a drop-in permissive connector library. |
| [n8n](https://github.com/n8n-io/n8n) | Sustainable Use / enterprise terms | Workflow reference; embedding requires separate license consideration. |
| [MCP Apps](https://github.com/modelcontextprotocol/ext-apps) | New code Apache 2.0; legacy MIT and documentation CC BY 4.0 notices | A portable future extension interface, not a replacement for vendor authorization. |
| [OpenAI app examples](https://github.com/openai/openai-apps-sdk-examples) | MIT examples | Useful host/UI patterns; does not confer access to a user's connected accounts. |

[OpenAI's connector documentation](https://developers.openai.com/api/docs/guides/tools-connectors-mcp)
requires the application to register OAuth clients and obtain vendor authorization
separately. It also deprecates legacy `connector_id` support for models released
after September 1, 2026. Prefer the portable MCP route for a future extension.
The [official app quickstart](https://developers.openai.com/plugins/build/app-quickstart)
was inspected. The direct ChatGPT marketplace page stopped at its browser
verification screen; its catalog was not inspected or installed.

No third-party source code or new dependency was added by this change. Existing
Activepieces attribution remains in the Google/Microsoft connection docs.

## Activation sequence and acceptance

| Milestone | Existing implementation | Remaining work and concrete acceptance |
| --- | --- | --- |
| Google/Gmail | Confidential web OAuth client, PKCE, encrypted tokens, bounded inbox metadata | Register/reuse an approved Google web client, set exact callback, store private secret and custody key, rebuild native public inputs. Consent with the designated test account, read invented email metadata, reopen and disconnect. |
| Microsoft/Outlook | One work/school tenant, OAuth, bounded email and seven-day calendar summaries | Register/reuse an approved Entra app for that tenant; configure secret, custody key and native public inputs. Consent, read invented email/event summaries, reopen and disconnect. Consumer accounts and arbitrary customer tenants are not implemented. |
| Scheduling | Separate Google staff login, membership/enrollment and scheduling connector | Configure its separate Google client, confirm the intended practice membership, then prove sign-in, appointment selection and return to the notebook. Gmail consent does not grant Scheduling access. |
| Messaging/fax | Spruce, SRFax and Documo managed transport adapters | Select approved provider accounts and test recipients, install reviewed account/secret bindings, then prove one synthetic delivery, status and recovery without duplicate sending. Fresh Spruce/SRFax public documentation returned 403; provider contracts must be verified before activation. |
| Payments | Stripe transport creates an unconfirmed PaymentIntent | Use approved Stripe test mode and invented customers/amounts; verify request creation and idempotency. This is not yet a complete hosted payment-link delivery/collection flow. |
| Patient portals | Account/workflow registry and reviewed work substrate | Select a specific supported portal and implement/verify its transport. A generic portal URL is not a connector; no universal portal integration is claimed. |

Google Gmail metadata uses a restricted scope; see the
[official scope classification](https://developers.google.com/workspace/gmail/api/auth/scopes).
Provider test-user setup and any required public-app verification remain separate
activation requirements. Microsoft's current scopes are delegated; tenant consent
policy can require administrator action.

## Exact first activation configuration

Reuse `scripts/prepare-operational-startup.py --connections` and the existing
[operational connector inputs](../operational-connectors.md). Do not create a
parallel secret or token-management platform.

- Google callback: `https://api.staging.cosmas.ai/connections/google/callback`.
  Scopes: `openid email https://www.googleapis.com/auth/gmail.metadata`.
- Microsoft callback: `https://api.staging.cosmas.ai/connections/microsoft/callback`.
  Scopes: `offline_access User.Read Mail.Read Calendars.Read`.
- Return origin: `https://staging.cosmas.ai`.
- Each provider needs its own private client secret and 32-byte encrypted-custody
  key, referenced by immutable Key Vault versions. Only public client/tenant and
  callback values belong in native builds. Do not put credentials in this repo.
- The reviewed input generator produces provider registration and native argument
  files, preserving the complete baseline configuration. These files do not
  create registrations or grant consent themselves.

No suitable CosmaBot mail app appeared in the read-only Entra inventory filtered
to names beginning with `Cosma`; this is not an exhaustive tenant inventory.
An existing Core API registration must not silently gain mail/calendar access.

## Rollout and boundaries

1. Merge the locally checked interface/catalog change. Build the API and shared
   hosted/native clients from the same source selection.
2. Within a renewed CosmaBot maintenance window, deploy the additive API first,
   then web at `staging.cosmas.ai`; preserve feature settings. Verify health,
   signed catalog results and setup-needed guides. No migration is required.
3. Install matching native updates when appropriate. Older API versions yield a
   retryable availability warning rather than a false connected state.
4. After approval for exact provider registration/access, install the reviewed
   private configuration, rebuild native public OAuth inputs and perform the
   small account acceptance flow above. Enable other groups as their accounts and
   actual transports are ready.
5. Roll back using the prior API/web/native selection if health or account
   recovery regresses. This change does not alter token storage or existing data.

No deployment, provider consent, email/calendar retrieval, message, payment,
Scribe capture or Core change is part of this local change. Scribe's full synthetic
encounter test remains deferred at the owner's request. The prior 90-minute
maintenance window expired at 2026-09-28 22:44:39 UTC.

Validation covers the shared interface, catalog authorization/contract, bounded
native route, stale-account recovery and a production web build. Desktop and
390px mobile previews use the real source components with invented connection
responses; they are not evidence of live OAuth or physical-device acceptance.
