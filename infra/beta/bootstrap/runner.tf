resource "azurerm_subnet" "deploy_runner" {
  name                 = local.runner_subnet_name
  resource_group_name  = azurerm_resource_group.state.name
  virtual_network_name = azurerm_virtual_network.state.name
  address_prefixes     = var.state_runner_subnet_prefixes

  default_outbound_access_enabled = false
}

resource "azurerm_network_security_group" "deploy_runner" {
  name                = local.runner_nsg_name
  resource_group_name = azurerm_resource_group.state.name
  location            = azurerm_resource_group.state.location
  tags                = merge(local.tags, { component = "protected-deploy-runner" })

  security_rule {
    name                       = "AllowPrivateDeploymentPorts"
    priority                   = 100
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_ranges    = ["443", "5432", "10000"]
    source_address_prefix      = "VirtualNetwork"
    destination_address_prefix = "VirtualNetwork"
  }

  security_rule {
    name                       = "AllowAzureInstanceMetadata"
    priority                   = 105
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "80"
    source_address_prefix      = "*"
    destination_address_prefix = "169.254.169.254"
  }

  security_rule {
    name                       = "AllowAzureWireServer"
    priority                   = 106
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_ranges    = ["80", "32526"]
    source_address_prefix      = "*"
    destination_address_prefix = "168.63.129.16"
  }

  security_rule {
    name                       = "AllowAzureDnsUdp"
    priority                   = 110
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Udp"
    source_port_range          = "*"
    destination_port_range     = "53"
    source_address_prefix      = "*"
    destination_address_prefix = "AzurePlatformDNS"
  }

  security_rule {
    name                       = "AllowAzureDnsTcp"
    priority                   = 120
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "53"
    source_address_prefix      = "*"
    destination_address_prefix = "AzurePlatformDNS"
  }

  security_rule {
    name                       = "AllowHttpsEgress"
    priority                   = 130
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "*"
    destination_address_prefix = "Internet"
  }

  security_rule {
    name                       = "DenyOtherOutbound"
    priority                   = 4095
    direction                  = "Outbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }

  security_rule {
    name                       = "DenyAllInbound"
    priority                   = 4096
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }
}

resource "azurerm_subnet_network_security_group_association" "deploy_runner" {
  subnet_id                 = azurerm_subnet.deploy_runner.id
  network_security_group_id = azurerm_network_security_group.deploy_runner.id
}

resource "azurerm_public_ip" "deploy_runner_egress" {
  name                = local.runner_public_ip_name
  resource_group_name = azurerm_resource_group.state.name
  location            = azurerm_resource_group.state.location
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = merge(local.tags, { component = "protected-deploy-runner-egress" })
}

resource "azurerm_nat_gateway" "deploy_runner" {
  name                    = local.runner_nat_name
  resource_group_name     = azurerm_resource_group.state.name
  location                = azurerm_resource_group.state.location
  sku_name                = "Standard"
  idle_timeout_in_minutes = 4
  tags                    = merge(local.tags, { component = "protected-deploy-runner" })
}

resource "azurerm_nat_gateway_public_ip_association" "deploy_runner" {
  nat_gateway_id       = azurerm_nat_gateway.deploy_runner.id
  public_ip_address_id = azurerm_public_ip.deploy_runner_egress.id
}

resource "azurerm_subnet_nat_gateway_association" "deploy_runner" {
  subnet_id      = azurerm_subnet.deploy_runner.id
  nat_gateway_id = azurerm_nat_gateway.deploy_runner.id
}

resource "azurerm_network_interface" "deploy_runner" {
  name                = local.runner_nic_name
  resource_group_name = azurerm_resource_group.state.name
  location            = azurerm_resource_group.state.location
  tags                = merge(local.tags, { component = "protected-deploy-runner" })

  ip_configuration {
    name                          = "private"
    subnet_id                     = azurerm_subnet.deploy_runner.id
    private_ip_address_allocation = "Dynamic"
  }

  depends_on = [
    azurerm_subnet_nat_gateway_association.deploy_runner,
    azurerm_subnet_network_security_group_association.deploy_runner,
  ]
}

resource "azurerm_linux_virtual_machine" "deploy_runner" {
  name                = local.runner_vm_name
  resource_group_name = azurerm_resource_group.state.name
  location            = azurerm_resource_group.state.location
  size                = var.runner_vm_size
  admin_username      = var.runner_admin_username

  network_interface_ids = [azurerm_network_interface.deploy_runner.id]

  disable_password_authentication = true
  provision_vm_agent              = true
  allow_extension_operations      = true
  secure_boot_enabled             = true
  vtpm_enabled                    = true

  admin_ssh_key {
    username   = var.runner_admin_username
    public_key = trimspace(var.runner_admin_ssh_public_key)
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.deploy.id]
  }

  os_disk {
    name                 = "osdisk-${local.runner_vm_name}"
    caching              = "ReadWrite"
    storage_account_type = "StandardSSD_LRS"
    disk_size_gb         = 32
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts-gen2"
    version   = var.runner_image_version
  }

  boot_diagnostics {}

  tags = merge(local.tags, {
    component    = "protected-deploy-runner"
    control_path = "azure-run-command"
  })

  lifecycle {
    precondition {
      condition     = length(azurerm_network_interface.deploy_runner.ip_configuration) == 1
      error_message = "The protected runner must have exactly one private-only NIC configuration."
    }
  }
}
