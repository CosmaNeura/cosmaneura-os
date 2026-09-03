locals {
  tags = {
    track   = "B"
    product = "cosmas-os"
    env     = "synth_os"
    phi     = "false"
    managed = "terraform"
  }

  # ACR names: 5-50 alphanumeric, globally unique.
  acr_name = substr(replace(lower("${var.name_prefix}acr${random_string.suffix.result}"), "-", ""), 0, 50)

  storage_name = substr(replace(lower("${var.name_prefix}st${random_string.suffix.result}"), "-", ""), 0, 24)

  kv_name = substr(replace(lower("kv-${var.name_prefix}-${random_string.suffix.result}"), "-", ""), 0, 24)

  redis_name    = "redis-${var.name_prefix}-${random_string.suffix.result}"
  postgres_name = "pg-${var.name_prefix}-${random_string.suffix.result}"
  law_name      = "law-${var.name_prefix}-${random_string.suffix.result}"
  cae_name      = "cae-${var.name_prefix}-${random_string.suffix.result}"
  api_app_name  = "ca-api-${var.name_prefix}"
  worker_name   = "ca-worker-${var.name_prefix}"
  identity_name = "id-${var.name_prefix}"
}

resource "random_string" "suffix" {
  length  = 6
  upper   = false
  special = false
}
