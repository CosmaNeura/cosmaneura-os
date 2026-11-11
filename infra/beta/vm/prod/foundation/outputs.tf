output "foundation" {
  description = "Public resource coordinates only. No secret, state, backup or account-key values."
  value = {
    profile                = "cosmabot-vm-prod-v1"
    location               = var.location
    resource_group_name    = azurerm_resource_group.production.name
    state_namespace        = terraform_data.state_namespace.output
    vm_id                  = azurerm_linux_virtual_machine.workload.id
    vm_name                = azurerm_linux_virtual_machine.workload.name
    vm_size                = azurerm_linux_virtual_machine.workload.size
    public_ip              = azurerm_public_ip.workload.ip_address
    data_disk_id           = azurerm_managed_disk.data.id
    data_disk_lun          = azurerm_virtual_machine_data_disk_attachment.data.lun
    vnet_id                = azurerm_virtual_network.production.id
    runtime_identity_id    = azurerm_user_assigned_identity.runtime.id
    runtime_client_id      = azurerm_user_assigned_identity.runtime.client_id
    runtime_principal_id   = azurerm_user_assigned_identity.runtime.principal_id
    registry_id            = azurerm_container_registry.production.id
    registry_login_server  = azurerm_container_registry.production.login_server
    key_vault_id           = azurerm_key_vault.production.id
    key_vault_uri          = azurerm_key_vault.production.vault_uri
    application_storage_id = azurerm_storage_account.objects["application"].id
    application_blob_url   = azurerm_storage_account.objects["application"].primary_blob_endpoint
    application_container  = azurerm_storage_container.objects["application"].name
    backup_storage_id      = azurerm_storage_account.objects["backup"].id
    backup_blob_url        = azurerm_storage_account.objects["backup"].primary_blob_endpoint
    backup_container       = azurerm_storage_container.objects["backup"].name
    log_workspace_id       = azurerm_log_analytics_workspace.production.id
    private_dns_zone_ids   = { for key, zone in azurerm_private_dns_zone.service : key => zone.id }
    private_endpoint_ids   = { for key, endpoint in azurerm_private_endpoint.service : key => endpoint.id }
    bootstrap_required     = true
    application_deployed   = false
  }
}
