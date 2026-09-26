# CosmaBot source integration — September 25, 2026

GitHub `main` remained at September 4 while the combined CosmaBot implementation
advanced in isolated local snapshots. This branch restores that implementation
to the owning `cosmaneura-os` repository so it can be reviewed and integrated.
It is not a deployment or a claim that operational beta acceptance is complete.

The source baseline combines the W97 OS backend and W97 standalone client.
It includes provider workspace/chat, configurable teams, invited-member access,
public Research, connection setup and operational work. The latest W98 team
setup improvement is a separate commit: opening Review checks settings
automatically and presents available capabilities before explicit confirmation
and Save. Source imports are bound by the accompanying SHA-256 inventory.

Core and Scribe server code are not copied into this repository. Existing
CosmaBot adapters and reused capture client components remain frozen. The
[application boundary](../COSMABOT_ARCHITECTURE.md) preserves the platform as
the owner of clinical features and Scribe as a main connector.

Two previously separate build contexts are combined without broadening them:
the root `.dockerignore` retains the API context, and
`Dockerfile.web.dockerignore` retains the web context. The web build also needs
the `clients/capture` dependencies required by the shared renderer. Native
installation, signing and account-specific configuration remain separate.

## Existing evidence reused

- W98 team setup: 103 relevant checks and TypeScript; 31 affected UI checks
  after the final wording change. Actual React review/confirmation/Save checks
  passed at 1440×1100 and 390×844 with no horizontal overflow.
- Current Research adapter: real generic public queries returned five PubMed,
  five ClinicalTrials.gov, two DailyMed and five RxNorm records. Each lookup
  completed in under 1.3 seconds in that run.
- Research API: current migrations and a fresh isolated PostgreSQL database
  completed lookup, selected-source save and fresh-session history/recovery.
  One selected source retained its URL and content hash. Identity and workspace
  admission were explicit synthetic seams; no hosted sign-in claim follows.

These are bounded checks of their stated behavior. They do not establish full
release review, physical-device acceptance, all connected-account workflows,
clinical output quality, deployment readiness or all repository checks. Exact
integration-check commands, results and commit identities are recorded with the
pull request. No credentials, live patient records, local databases or generated
application archives belong in this import.
