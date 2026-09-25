# Application and database release binding

`release-schema.json` belongs to the selected release, alongside the application
source and immutable image selection. Both variable validation and the workload
precondition read it. The current assembled release requires `c83a2f19b650`,
including preparation retirement history. Earlier `0002_external_identities`,
`e5917a2c64bd` and `f72b834c1e90` gates reject this release even after a successful
migration.

The local source-contract regression checks this file against the runtime
readiness constant and the complete graph of 43 current Alembic migrations.
Advance it only in a new release whose source, migration graph and selected image
were built and qualified together.
It is deliberately not an operator-overridable Terraform variable.

No migration runs during input preparation. Keep the existing manually executed,
forward-only preparation job and actual evidence collection. An attestation must
still bind the selected image digest, expected schema, practice Box, database
server and exact preparation job execution. Missing or stale evidence refuses
workload activation. The root's remaining identity, network, evidence, secret and
deployment controls continue to apply.
