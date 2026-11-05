output "allocator_host" {
  description = "Held-by-default allocator identity/subnet coordinates. Empty IDs while create_resources is false."
  value = {
    contract_version              = "cosmabot.private-worker-allocator-host.v1"
    environment                   = var.environment
    create_resources              = var.create_resources
    resources_created             = var.create_resources
    worker_started                = false
    hosting_configuration_enabled = false
    p2_extra_box_authorized       = false
    stripe_live_mode              = false
    practice_uuid_limit           = 1
    identity_name                 = local.identity_name
    subnet_name                   = local.subnet_name
    worker_client_id              = try(azurerm_user_assigned_identity.allocator[0].client_id, null)
    worker_object_id              = try(azurerm_user_assigned_identity.allocator[0].principal_id, null)
    host_subnet_id                = try(azurerm_subnet.allocator_host[0].id, null)
  }
}
