# Selected with the application source and image; validate_release_schema.py
# verifies this metadata against the runtime and complete migration graph.
# This is release metadata, never operator-supplied evidence of a migration.
locals {
  database_release = jsondecode(file("${path.module}/release-schema.json"))

  database_preparation_matches_release = try(
    var.database_preparation_attestation.image_digest == var.image_digest &&
    var.database_preparation_attestation.schema_revision == local.database_release.schema_revision &&
    lower(var.database_preparation_attestation.box_id) == lower(var.box_id) &&
    lower(var.database_preparation_attestation.database_server_id) == lower(local.expected_database_server_id) &&
    startswith(
      lower(var.database_preparation_attestation.execution_id),
      "${lower(local.expected_database_job_id)}/executions/",
    ),
    false,
  )
}
