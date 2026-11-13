variable "bootstrap_key_file" {
  type        = string
  description = "0600 generated passphrase file in the fresh private local bootstrap directory; never a passphrase argument."
  validation {
    condition     = startswith(var.bootstrap_key_file, "/") && endswith(var.bootstrap_key_file, "/encryption.passphrase")
    error_message = "Use the private bootstrap encryption.passphrase file created by bootstrap_local.py."
  }
}
terraform {
  encryption {
    key_provider "pbkdf2" "local_bootstrap" {
      passphrase    = trimspace(file(var.bootstrap_key_file))
      key_length    = 32
      iterations    = 600000
      salt_length   = 32
      hash_function = "sha512"
    }
    method "aes_gcm" "local_bootstrap" {
      keys = key_provider.pbkdf2.local_bootstrap
    }
    state {
      method   = method.aes_gcm.local_bootstrap
      enforced = true
    }
    plan {
      method   = method.aes_gcm.local_bootstrap
      enforced = true
    }
  }
}
