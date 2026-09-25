resource "azurerm_linux_virtual_machine" "workload" {
  name                            = local.vm_name
  resource_group_name             = azurerm_resource_group.staging.name
  location                        = var.location
  size                            = "Standard_D2s_v5"
  admin_username                  = var.admin_username
  network_interface_ids           = [azurerm_network_interface.workload.id]
  disable_password_authentication = true
  provision_vm_agent              = true
  allow_extension_operations      = true
  secure_boot_enabled             = true
  vtpm_enabled                    = true
  admin_ssh_key {
    username   = var.admin_username
    public_key = trimspace(var.admin_ssh_public_key)
  }
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.runtime.id]
  }
  os_disk {
    name                 = "osdisk-${local.vm_name}"
    caching              = "ReadWrite"
    storage_account_type = "StandardSSD_LRS"
    disk_size_gb         = 64
  }
  source_image_reference {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts-gen2"
    version   = var.ubuntu_image_version
  }
  boot_diagnostics {}
  tags = merge(local.tags, { component = "staging-workload", control_path = "azure-run-command" })
  lifecycle { prevent_destroy = true }
}
resource "azurerm_managed_disk" "data" {
  name                          = "data-${local.vm_name}"
  resource_group_name           = azurerm_resource_group.staging.name
  location                      = var.location
  storage_account_type          = "StandardSSD_LRS"
  create_option                 = "Empty"
  disk_size_gb                  = 128
  network_access_policy         = "DenyAll"
  public_network_access_enabled = false
  tags                          = local.tags
  lifecycle { prevent_destroy = true }
}
resource "azurerm_virtual_machine_data_disk_attachment" "data" {
  managed_disk_id    = azurerm_managed_disk.data.id
  virtual_machine_id = azurerm_linux_virtual_machine.workload.id
  lun                = 0
  caching            = "None"
}
