locals {
  name_token = substr(replace(lower(var.beta_id), "-", ""), 0, 12)

  is_authorized_beta  = var.deployment_mode == "authorized_beta"
  data_classification = local.is_authorized_beta ? "phi-authorized" : "synthetic-only"

  state_resource_group_name    = "rg-cosmas-os-beta-state-${var.beta_id}"
  workload_resource_group_name = "rg-cosmas-os-beta-${var.beta_id}"
  deploy_identity_name         = "id-cosmas-os-beta-deploy-${var.beta_id}"
  state_vnet_name              = "vnet-cosmas-os-beta-state-${var.beta_id}"
  state_subnet_name            = "snet-private-endpoints"
  runner_subnet_name           = "snet-deploy-runner"
  runner_nsg_name              = "nsg-cosmas-os-beta-runner-${var.beta_id}"
  runner_nat_name              = "nat-cosmas-os-beta-runner-${var.beta_id}"
  runner_public_ip_name        = "pip-cosmas-os-beta-runner-egress-${var.beta_id}"
  runner_nic_name              = "nic-cosmas-os-beta-runner-${var.beta_id}"
  runner_vm_name               = "vm-cosmas-os-beta-runner-${var.beta_id}"
  # Reserve all six random characters inside the globally unique 24-character limit.
  state_storage_account_name = "cmbetatf${local.name_token}${random_string.suffix.result}"

  tags = {
    track               = "B"
    product             = "cosmas-os"
    env                 = "early_adopter_beta"
    deployment_mode     = var.deployment_mode
    data_classification = local.data_classification
    box_scope           = "dedicated"
    box_id              = var.box_id
    managed             = "terraform"
  }
}

resource "random_string" "suffix" {
  length  = 6
  upper   = false
  special = false
}

resource "terraform_data" "prerequisite_guard" {
  input = {
    deployment_mode = var.deployment_mode
    evidence_digest = nonsensitive(sha256(join("|", [
      var.clinic_legal_name == null ? "" : var.clinic_legal_name,
      var.baa_evidence_reference == null ? "" : var.baa_evidence_reference,
      var.phi_authorization_reference == null ? "" : var.phi_authorization_reference,
      var.human_deploy_evidence_reference,
      var.region_evidence_reference,
      var.runner_network_evidence_reference,
    ])))
  }

  lifecycle {
    precondition {
      condition     = !local.is_authorized_beta || try(length(trimspace(var.clinic_legal_name)), 0) >= 3
      error_message = "authorized_beta requires a real named clinic/covered entity before any D3 Azure mutation."
    }
    precondition {
      condition     = !local.is_authorized_beta || try(length(trimspace(var.baa_evidence_reference)), 0) >= 3
      error_message = "authorized_beta requires applicable BAA evidence before any D3 Azure mutation."
    }
    precondition {
      condition     = !local.is_authorized_beta || try(length(trimspace(var.phi_authorization_reference)), 0) >= 3
      error_message = "authorized_beta requires a separate human PHI authorization reference before any D3 Azure mutation."
    }
    precondition {
      condition     = length(trimspace(var.human_deploy_evidence_reference)) >= 3
      error_message = "Human deploy approval evidence must be recorded before any D3 Azure mutation."
    }
    precondition {
      condition     = length(trimspace(var.region_evidence_reference)) >= 3
      error_message = "Region, residency, quota, and SKU evidence must be recorded before any D3 Azure mutation."
    }
    precondition {
      condition     = length(trimspace(var.runner_network_evidence_reference)) >= 3
      error_message = "The protected-runner private state, DNS, NSG, and NAT design must be reviewed before bootstrap."
    }
  }
}

# Once an environment has entered authorized_beta, a normal plan cannot relabel
# it synthetic while retained data may still be PHI. Downgrade requires a
# separately reviewed decommission/reclassification procedure and code change.
resource "terraform_data" "authorized_beta_mode_lock" {
  count = local.is_authorized_beta ? 1 : 0

  input = {
    deployment_mode     = var.deployment_mode
    data_classification = local.data_classification
    box_id              = var.box_id
  }

  depends_on = [terraform_data.prerequisite_guard]

  lifecycle {
    prevent_destroy = true
  }
}
