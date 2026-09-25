# Hosted desktop and iPhone workspace

The ordinary API now supports the Scribe/private-team workspace in the existing
`early_adopter_beta` environment. Set `WORKSPACE_ENABLED`,
`WORKSPACE_AUTHENTICATED_ENABLED` and `WORKSPACE_HOSTED_ENABLED` together.
`.env.hosted.example` lists the required settings. The example deliberately has
empty identity, storage, database and approval values; it cannot start a service.

The profile retains the existing dedicated Box, reviewed Clerk bindings, exact
issuer/JWKS/audience/organization, authenticated TLS PostgreSQL/Redis, Azure Blob,
and deployment evidence requirements. Authorized clinical data additionally
requires the existing clinic, BAA and PHI authorization references. Configuration
never provisions a user, creates an account mapping or authorizes a connector.
Local synthetic flags cannot be combined with the hosted profile.

HTTPS browser origins are explicit. Admit `capacitor://localhost` only with
`WORKSPACE_APPLE_HOSTED_TRANSPORT_ENABLED`; admit `app://cosmas` only with
`WORKSPACE_DESKTOP_HOSTED_TRANSPORT_ENABLED`. Each admitted native origin must
also appear in `CLERK_AUTHORIZED_PARTIES`. The native authorized parties are JWT
claims, not substitutes for signature, current membership or private ownership.

Start the ordinary application with
`uvicorn cosmas_os.api.app:app --host 0.0.0.0 --port 8000` after applying its ordinary
migrations and reviewed identity bootstrap. `/ready` checks the exact shipped
schema revision. New hosted notebooks start empty: the local rehearsal's fixed
invented preparation is not inserted. Existing saved notebooks and replay
receipts are retained.

The client uses one public build profile for browser, desktop or Apple. Its exact
API origin is compiled into the bundle. Browser tokens are restricted to the
configured HTTPS API and page origin. Apple keeps WebKit fetch, abort, redirect
and CORS handling. Desktop keeps tokens in the native/main-process boundary and
uses HTTPS with hostname/certificate verification; the renderer still addresses
only its closed `app://cosmas/api` bridge. A hosted desktop installation records
its backend and data mode in its storage marker and refuses a different backend
without rewriting saved data.

The current native hosted profile is a synthetic development profile using the
existing native test-identity adapter. It is not authorized-data native release
or a signed distribution. The web profile retains production Clerk key checks
for authorized data. Native login, physical capture and update/distribution
acceptance are still required separately.

The shared UI, native composers and desktop packager consume
`cosmas-workspace-build.json`, generated from the same build configuration as the
bundle. A mismatched native/API/web composition is refused. Server credentials
never belong in that file or in `VITE_*` values. The iPhone hosted composition
removes the local-network transport exception and pins its HTTPS API and optional
upload origins in CSP. The local compositions retain their original behavior.

The deployment derivative reuses the existing Azure environment, private data
services and deployment controls. Its additional workspace settings configure
both API and worker, plus the exact client origins. It has not been applied.
The API image retains the pinned Python/wheel lock. The web image now includes
the retained capture dependencies and shared configuration, uses pinned Node
24.19, and pins the capture package manager to the existing 9.15.9 lockfile.

Still needed for operational use: current Core encounters and reviewed identity
mappings; complete service-profile provisioning for capture/Scheduling/vendors;
real sign-in and provider acceptance; cloud rollout and restore/update acceptance.
The hosted profile makes these components deployable together; it does not
establish those outcomes by enabling a flag.
