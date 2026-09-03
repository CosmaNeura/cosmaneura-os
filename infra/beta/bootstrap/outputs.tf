output "subscription_id" {
  value = var.subscription_id
}

output "tenant_id" {
  value = var.tenant_id
}

output "deployment_mode" {
  value = var.deployment_mode
}

output "data_classification" {
  value = local.data_classification
}

output "box_id" {
  description = "Exact dedicated logical Box UUID that every environment plan must inherit."
  value       = var.box_id
}

output "backend_resource_group_name" {
  value = azurerm_resource_group.state.name
}

output "backend_storage_account_name" {
  value = azurerm_storage_account.state.name
}

output "backend_container_name" {
  description = "Private container created after bootstrap from the protected runner, never from the unpeered bootstrap workstation."
  value       = "tfstate"
}

output "backend_key" {
  value = "early-adopter-beta/${var.beta_id}/terraform.tfstate"
}

output "workload_resource_group_name" {
  value = azurerm_resource_group.workload.name
}

output "deploy_identity_client_id" {
  value = azurerm_user_assigned_identity.deploy.client_id
}

output "deploy_identity_principal_id" {
  value = azurerm_user_assigned_identity.deploy.principal_id
}

output "state_vnet_id" {
  value = azurerm_virtual_network.state.id
}

output "state_blob_private_dns_zone_id" {
  value = azurerm_private_dns_zone.state_blob.id
}

output "state_blob_private_endpoint_id" {
  description = "Exact state Blob private endpoint used by protected-runner DNS evidence."
  value       = azurerm_private_endpoint.state_blob.id
}

output "state_private_endpoint_subnet_id" {
  description = "Exact subnet containing only the state Blob private endpoint."
  value       = azurerm_subnet.state_private_endpoints.id
}

output "runner_vm_name" {
  value = azurerm_linux_virtual_machine.deploy_runner.name
}

output "runner_image_version" {
  value = var.runner_image_version
}

output "runner_vm_size" {
  value = var.runner_vm_size
}

output "runner_subnet_id" {
  value = azurerm_subnet.deploy_runner.id
}

output "runner_network_security_group_id" {
  value = azurerm_network_security_group.deploy_runner.id
}

output "runner_nat_gateway_id" {
  value = azurerm_nat_gateway.deploy_runner.id
}

output "runner_egress_public_ip_id" {
  value = azurerm_public_ip.deploy_runner_egress.id
}

output "runner_private_ip_address" {
  value = azurerm_network_interface.deploy_runner.private_ip_address
}

output "runner_egress_ip_address" {
  description = "Dedicated NAT egress IP for human review and outbound allow-listing; it is not attached to the VM."
  value       = azurerm_public_ip.deploy_runner_egress.ip_address
}
