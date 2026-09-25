// Generated from the existing public Python contract. Do not hand-edit shapes.
// Relational checks and exact commitments are in finance-setup-contract.ts.
// Source SHA-256: 0c564b34ce4fcd8e8c8de4ccabdddf92808fb96b221ef92458f0f956f9504c2f
export const FINANCE_SETUP_SCHEMAS = {
  "AccountProposal": {
    "additionalProperties": false,
    "properties": {
      "setup_id": {
        "title": "Setup Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "expected_version": {
        "maximum": 2147483647,
        "minimum": 0,
        "title": "Expected Version",
        "type": "integer"
      },
      "idempotency_key": {
        "maxLength": 100,
        "minLength": 8,
        "pattern": "^[A-Za-z0-9:_-]+$",
        "title": "Idempotency Key",
        "type": "string"
      },
      "installation_id": {
        "title": "Installation Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "installation_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Installation Sha256",
        "type": "string"
      },
      "label": {
        "maxLength": 80,
        "title": "Label",
        "type": "string",
        "x-rules": [
          "_text"
        ]
      },
      "permissions": {
        "$ref": "#/$defs/Permissions"
      }
    },
    "required": [
      "setup_id",
      "expected_version",
      "idempotency_key",
      "installation_id",
      "installation_sha256",
      "label",
      "permissions"
    ],
    "title": "AccountProposal",
    "type": "object",
    "x-no-null": true
  },
  "AccountReview": {
    "additionalProperties": false,
    "properties": {
      "kind": {
        "const": "account",
        "title": "Kind",
        "type": "string"
      },
      "setup_id": {
        "title": "Setup Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "revision_id": {
        "title": "Revision Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "revision": {
        "maximum": 2147483647,
        "minimum": 1,
        "title": "Revision",
        "type": "integer"
      },
      "installed": {
        "$ref": "#/$defs/InstalledAccount"
      },
      "label": {
        "maxLength": 80,
        "title": "Label",
        "type": "string",
        "x-rules": [
          "_text"
        ]
      },
      "permissions": {
        "$ref": "#/$defs/Permissions"
      },
      "connection_version_id": {
        "title": "Connection Version Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      }
    },
    "required": [
      "kind",
      "setup_id",
      "revision_id",
      "revision",
      "installed",
      "label",
      "permissions",
      "connection_version_id"
    ],
    "title": "AccountReview",
    "type": "object",
    "x-no-null": false
  },
  "AccountTarget": {
    "additionalProperties": false,
    "properties": {
      "kind": {
        "const": "account",
        "title": "Kind",
        "type": "string"
      },
      "installation_id": {
        "title": "Installation Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      }
    },
    "required": [
      "kind",
      "installation_id"
    ],
    "title": "AccountTarget",
    "type": "object",
    "x-no-null": false
  },
  "Activation": {
    "additionalProperties": false,
    "properties": {
      "setup_id": {
        "title": "Setup Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "expected_version": {
        "maximum": 2147483647,
        "minimum": 1,
        "title": "Expected Version",
        "type": "integer"
      },
      "revision_id": {
        "title": "Revision Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "review_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Review Sha256",
        "type": "string"
      },
      "idempotency_key": {
        "maxLength": 100,
        "minLength": 8,
        "pattern": "^[A-Za-z0-9:_-]+$",
        "title": "Idempotency Key",
        "type": "string"
      },
      "reviewed_account": {
        "const": true,
        "title": "Reviewed Account",
        "type": "boolean",
        "x-rules": [
          "_true"
        ]
      },
      "reviewed_environment": {
        "const": true,
        "title": "Reviewed Environment",
        "type": "boolean",
        "x-rules": [
          "_true"
        ]
      },
      "reviewed_patient_customer": {
        "anyOf": [
          {
            "const": true,
            "type": "boolean",
            "x-rules": [
              "_true"
            ]
          },
          {
            "type": "null"
          }
        ],
        "default": null,
        "title": "Reviewed Patient Customer"
      },
      "confirm_local_activation": {
        "const": true,
        "title": "Confirm Local Activation",
        "type": "boolean",
        "x-rules": [
          "_true"
        ]
      }
    },
    "required": [
      "setup_id",
      "expected_version",
      "revision_id",
      "review_sha256",
      "idempotency_key",
      "reviewed_account",
      "reviewed_environment",
      "confirm_local_activation"
    ],
    "title": "Activation",
    "type": "object",
    "x-no-null": true
  },
  "Binding": {
    "additionalProperties": false,
    "properties": {
      "setup_id": {
        "title": "Setup Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "expected_version": {
        "maximum": 2147483647,
        "minimum": 1,
        "title": "Expected Version",
        "type": "integer"
      },
      "revision_id": {
        "title": "Revision Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "review_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Review Sha256",
        "type": "string"
      }
    },
    "required": [
      "setup_id",
      "expected_version",
      "revision_id",
      "review_sha256"
    ],
    "title": "Binding",
    "type": "object",
    "x-no-null": true
  },
  "Bound": {
    "additionalProperties": false,
    "properties": {
      "setup_id": {
        "title": "Setup Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "expected_version": {
        "maximum": 2147483647,
        "minimum": 1,
        "title": "Expected Version",
        "type": "integer"
      },
      "revision_id": {
        "title": "Revision Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "review_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Review Sha256",
        "type": "string"
      },
      "idempotency_key": {
        "maxLength": 100,
        "minLength": 8,
        "pattern": "^[A-Za-z0-9:_-]+$",
        "title": "Idempotency Key",
        "type": "string"
      }
    },
    "required": [
      "setup_id",
      "expected_version",
      "revision_id",
      "review_sha256",
      "idempotency_key"
    ],
    "title": "Bound",
    "type": "object",
    "x-no-null": true
  },
  "Catalog": {
    "additionalProperties": false,
    "properties": {
      "contract_version": {
        "const": 1,
        "title": "Contract Version",
        "type": "integer"
      },
      "scope": {
        "$ref": "#/$defs/Scope"
      },
      "enabled": {
        "title": "Enabled",
        "type": "boolean"
      },
      "installed_accounts": {
        "items": {
          "$ref": "#/$defs/InstalledAccount"
        },
        "maxItems": 50,
        "title": "Installed Accounts",
        "type": "array"
      },
      "patients": {
        "items": {
          "$ref": "#/$defs/Patient"
        },
        "maxItems": 100,
        "title": "Patients",
        "type": "array"
      },
      "setups": {
        "items": {
          "$ref": "#/$defs/Summary"
        },
        "maxItems": 50,
        "title": "Setups",
        "type": "array"
      }
    },
    "required": [
      "contract_version",
      "scope",
      "enabled",
      "installed_accounts",
      "patients",
      "setups"
    ],
    "title": "Catalog",
    "type": "object",
    "x-no-null": false
  },
  "CustomerProposal": {
    "additionalProperties": false,
    "properties": {
      "setup_id": {
        "title": "Setup Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "expected_version": {
        "maximum": 2147483647,
        "minimum": 0,
        "title": "Expected Version",
        "type": "integer"
      },
      "idempotency_key": {
        "maxLength": 100,
        "minLength": 8,
        "pattern": "^[A-Za-z0-9:_-]+$",
        "title": "Idempotency Key",
        "type": "string"
      },
      "account": {
        "$ref": "#/$defs/Binding"
      },
      "patient_link_id": {
        "title": "Patient Link Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "customer_id": {
        "pattern": "^cus_[A-Za-z0-9]{1,240}$",
        "title": "Customer Id",
        "type": "string"
      },
      "label": {
        "maxLength": 80,
        "title": "Label",
        "type": "string",
        "x-rules": [
          "_text"
        ]
      }
    },
    "required": [
      "setup_id",
      "expected_version",
      "idempotency_key",
      "account",
      "patient_link_id",
      "customer_id",
      "label"
    ],
    "title": "CustomerProposal",
    "type": "object",
    "x-no-null": true
  },
  "CustomerReview": {
    "additionalProperties": false,
    "properties": {
      "kind": {
        "const": "customer",
        "title": "Kind",
        "type": "string"
      },
      "setup_id": {
        "title": "Setup Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "revision_id": {
        "title": "Revision Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "revision": {
        "maximum": 2147483647,
        "minimum": 1,
        "title": "Revision",
        "type": "integer"
      },
      "installed": {
        "$ref": "#/$defs/InstalledAccount"
      },
      "label": {
        "maxLength": 80,
        "title": "Label",
        "type": "string",
        "x-rules": [
          "_text"
        ]
      },
      "account": {
        "$ref": "#/$defs/Binding"
      },
      "account_label": {
        "maxLength": 80,
        "title": "Account Label",
        "type": "string",
        "x-rules": [
          "_text"
        ]
      },
      "connection_version_id": {
        "title": "Connection Version Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "customer_version_id": {
        "title": "Customer Version Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "patient": {
        "$ref": "#/$defs/Patient"
      },
      "customer_id": {
        "pattern": "^cus_[A-Za-z0-9]{1,240}$",
        "title": "Customer Id",
        "type": "string"
      }
    },
    "required": [
      "kind",
      "setup_id",
      "revision_id",
      "revision",
      "installed",
      "label",
      "account",
      "account_label",
      "connection_version_id",
      "customer_version_id",
      "patient",
      "customer_id"
    ],
    "title": "CustomerReview",
    "type": "object",
    "x-no-null": false
  },
  "CustomerTarget": {
    "additionalProperties": false,
    "properties": {
      "kind": {
        "const": "customer",
        "title": "Kind",
        "type": "string"
      },
      "account_setup_id": {
        "title": "Account Setup Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "patient_link_id": {
        "title": "Patient Link Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      }
    },
    "required": [
      "kind",
      "account_setup_id",
      "patient_link_id"
    ],
    "title": "CustomerTarget",
    "type": "object",
    "x-no-null": false
  },
  "Detail": {
    "additionalProperties": false,
    "properties": {
      "contract_version": {
        "const": 1,
        "title": "Contract Version",
        "type": "integer"
      },
      "scope": {
        "$ref": "#/$defs/Scope"
      },
      "summary": {
        "$ref": "#/$defs/Summary"
      },
      "review": {
        "discriminator": {
          "mapping": {
            "account": "#/$defs/AccountReview",
            "customer": "#/$defs/CustomerReview"
          },
          "propertyName": "kind"
        },
        "oneOf": [
          {
            "$ref": "#/$defs/AccountReview"
          },
          {
            "$ref": "#/$defs/CustomerReview"
          }
        ],
        "title": "Review"
      },
      "last_receipt": {
        "$ref": "#/$defs/Receipt"
      }
    },
    "required": [
      "contract_version",
      "scope",
      "summary",
      "review",
      "last_receipt"
    ],
    "title": "Detail",
    "type": "object",
    "x-no-null": false
  },
  "Disable": {
    "additionalProperties": false,
    "properties": {
      "setup_id": {
        "title": "Setup Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "expected_version": {
        "maximum": 2147483647,
        "minimum": 1,
        "title": "Expected Version",
        "type": "integer"
      },
      "revision_id": {
        "title": "Revision Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "review_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Review Sha256",
        "type": "string"
      },
      "idempotency_key": {
        "maxLength": 100,
        "minLength": 8,
        "pattern": "^[A-Za-z0-9:_-]+$",
        "title": "Idempotency Key",
        "type": "string"
      },
      "confirm_disable": {
        "const": true,
        "title": "Confirm Disable",
        "type": "boolean",
        "x-rules": [
          "_true"
        ]
      }
    },
    "required": [
      "setup_id",
      "expected_version",
      "revision_id",
      "review_sha256",
      "idempotency_key",
      "confirm_disable"
    ],
    "title": "Disable",
    "type": "object",
    "x-no-null": true
  },
  "Effect": {
    "additionalProperties": false,
    "properties": {
      "setup_id": {
        "title": "Setup Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "kind": {
        "enum": [
          "account",
          "customer"
        ],
        "title": "Kind",
        "type": "string"
      },
      "version": {
        "maximum": 2147483647,
        "minimum": 1,
        "title": "Version",
        "type": "integer"
      },
      "revision_id": {
        "title": "Revision Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "review_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Review Sha256",
        "type": "string"
      },
      "state": {
        "enum": [
          "pending_review",
          "active",
          "disabled",
          "revoked"
        ],
        "title": "State",
        "type": "string"
      }
    },
    "required": [
      "setup_id",
      "kind",
      "version",
      "revision_id",
      "review_sha256",
      "state"
    ],
    "title": "Effect",
    "type": "object",
    "x-no-null": false
  },
  "History": {
    "additionalProperties": false,
    "properties": {
      "contract_version": {
        "const": 1,
        "title": "Contract Version",
        "type": "integer"
      },
      "scope": {
        "$ref": "#/$defs/Scope"
      },
      "setup_id": {
        "title": "Setup Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "receipts": {
        "items": {
          "$ref": "#/$defs/Receipt"
        },
        "maxItems": 100,
        "title": "Receipts",
        "type": "array"
      }
    },
    "required": [
      "contract_version",
      "scope",
      "setup_id",
      "receipts"
    ],
    "title": "History",
    "type": "object",
    "x-no-null": false
  },
  "InstalledAccount": {
    "additionalProperties": false,
    "properties": {
      "installation_id": {
        "title": "Installation Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "installation_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Installation Sha256",
        "type": "string"
      },
      "label": {
        "maxLength": 80,
        "title": "Label",
        "type": "string",
        "x-rules": [
          "_text"
        ]
      },
      "environment": {
        "enum": [
          "sandbox",
          "production"
        ],
        "title": "Environment",
        "type": "string"
      },
      "account_reference": {
        "pattern": "^acct_[A-Za-z0-9]{1,240}$",
        "title": "Account Reference",
        "type": "string"
      }
    },
    "required": [
      "installation_id",
      "installation_sha256",
      "label",
      "environment",
      "account_reference"
    ],
    "title": "InstalledAccount",
    "type": "object",
    "x-no-null": false
  },
  "NotFound": {
    "additionalProperties": false,
    "properties": {
      "contract_version": {
        "const": 1,
        "title": "Contract Version",
        "type": "integer"
      },
      "outcome": {
        "const": "not_found",
        "title": "Outcome",
        "type": "string"
      },
      "scope": {
        "$ref": "#/$defs/Scope"
      },
      "command_kind": {
        "enum": [
          "propose_account",
          "propose_customer",
          "activate",
          "disable",
          "revoke"
        ],
        "title": "Command Kind",
        "type": "string"
      },
      "idempotency_key": {
        "maxLength": 100,
        "minLength": 8,
        "pattern": "^[A-Za-z0-9:_-]+$",
        "title": "Idempotency Key",
        "type": "string"
      },
      "request_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Request Sha256",
        "type": "string"
      }
    },
    "required": [
      "contract_version",
      "outcome",
      "scope",
      "command_kind",
      "idempotency_key",
      "request_sha256"
    ],
    "title": "NotFound",
    "type": "object",
    "x-no-null": false
  },
  "Patient": {
    "additionalProperties": false,
    "properties": {
      "patient_link_id": {
        "title": "Patient Link Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "label": {
        "maxLength": 80,
        "title": "Label",
        "type": "string",
        "x-rules": [
          "_text"
        ]
      }
    },
    "required": [
      "patient_link_id",
      "label"
    ],
    "title": "Patient",
    "type": "object",
    "x-no-null": false
  },
  "Permissions": {
    "additionalProperties": false,
    "properties": {
      "read_status": {
        "title": "Read Status",
        "type": "boolean"
      },
      "create_unconfirmed_intents": {
        "title": "Create Unconfirmed Intents",
        "type": "boolean"
      }
    },
    "required": [
      "read_status",
      "create_unconfirmed_intents"
    ],
    "title": "Permissions",
    "type": "object",
    "x-no-null": true
  },
  "Receipt": {
    "additionalProperties": false,
    "properties": {
      "contract_version": {
        "const": 1,
        "title": "Contract Version",
        "type": "integer"
      },
      "outcome": {
        "const": "recorded",
        "title": "Outcome",
        "type": "string"
      },
      "scope": {
        "$ref": "#/$defs/Scope"
      },
      "command_kind": {
        "enum": [
          "propose_account",
          "propose_customer",
          "activate",
          "disable",
          "revoke"
        ],
        "title": "Command Kind",
        "type": "string"
      },
      "idempotency_key": {
        "maxLength": 100,
        "minLength": 8,
        "pattern": "^[A-Za-z0-9:_-]+$",
        "title": "Idempotency Key",
        "type": "string"
      },
      "request_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Request Sha256",
        "type": "string"
      },
      "receipt_id": {
        "title": "Receipt Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "recorded_at": {
        "title": "Recorded At",
        "type": "string",
        "x-rules": [
          "_timestamp"
        ]
      },
      "effect": {
        "$ref": "#/$defs/Effect"
      },
      "receipt_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Receipt Sha256",
        "type": "string"
      }
    },
    "required": [
      "contract_version",
      "outcome",
      "scope",
      "command_kind",
      "idempotency_key",
      "request_sha256",
      "receipt_id",
      "recorded_at",
      "effect",
      "receipt_sha256"
    ],
    "title": "Receipt",
    "type": "object",
    "x-no-null": false
  },
  "Resolve": {
    "additionalProperties": false,
    "properties": {
      "command_kind": {
        "enum": [
          "propose_account",
          "propose_customer",
          "activate",
          "disable",
          "revoke"
        ],
        "title": "Command Kind",
        "type": "string"
      },
      "idempotency_key": {
        "maxLength": 100,
        "minLength": 8,
        "pattern": "^[A-Za-z0-9:_-]+$",
        "title": "Idempotency Key",
        "type": "string"
      },
      "request_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Request Sha256",
        "type": "string"
      }
    },
    "required": [
      "command_kind",
      "idempotency_key",
      "request_sha256"
    ],
    "title": "Resolve",
    "type": "object",
    "x-no-null": true
  },
  "Revoke": {
    "additionalProperties": false,
    "properties": {
      "setup_id": {
        "title": "Setup Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "expected_version": {
        "maximum": 2147483647,
        "minimum": 1,
        "title": "Expected Version",
        "type": "integer"
      },
      "revision_id": {
        "title": "Revision Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "review_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Review Sha256",
        "type": "string"
      },
      "idempotency_key": {
        "maxLength": 100,
        "minLength": 8,
        "pattern": "^[A-Za-z0-9:_-]+$",
        "title": "Idempotency Key",
        "type": "string"
      },
      "confirm_revoke": {
        "const": true,
        "title": "Confirm Revoke",
        "type": "boolean",
        "x-rules": [
          "_true"
        ]
      }
    },
    "required": [
      "setup_id",
      "expected_version",
      "revision_id",
      "review_sha256",
      "idempotency_key",
      "confirm_revoke"
    ],
    "title": "Revoke",
    "type": "object",
    "x-no-null": true
  },
  "Scope": {
    "additionalProperties": false,
    "properties": {
      "box_id": {
        "title": "Box Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "owner_id": {
        "title": "Owner Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      }
    },
    "required": [
      "box_id",
      "owner_id"
    ],
    "title": "Scope",
    "type": "object",
    "x-no-null": false
  },
  "Summary": {
    "additionalProperties": false,
    "properties": {
      "setup_id": {
        "title": "Setup Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "kind": {
        "enum": [
          "account",
          "customer"
        ],
        "title": "Kind",
        "type": "string"
      },
      "version": {
        "maximum": 2147483647,
        "minimum": 1,
        "title": "Version",
        "type": "integer"
      },
      "revision_id": {
        "title": "Revision Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "review_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Review Sha256",
        "type": "string"
      },
      "state": {
        "enum": [
          "pending_review",
          "active",
          "disabled",
          "revoked"
        ],
        "title": "State",
        "type": "string"
      },
      "target": {
        "discriminator": {
          "mapping": {
            "account": "#/$defs/AccountTarget",
            "customer": "#/$defs/CustomerTarget"
          },
          "propertyName": "kind"
        },
        "oneOf": [
          {
            "$ref": "#/$defs/AccountTarget"
          },
          {
            "$ref": "#/$defs/CustomerTarget"
          }
        ],
        "title": "Target"
      },
      "label": {
        "maxLength": 80,
        "title": "Label",
        "type": "string",
        "x-rules": [
          "_text"
        ]
      },
      "usable_locally": {
        "title": "Usable Locally",
        "type": "boolean"
      },
      "availability": {
        "enum": [
          "available",
          "finance_setup_disabled",
          "finance_installation_changed",
          "finance_account_changed",
          "finance_patient_unavailable",
          "finance_binding_unavailable",
          "finance_setup_inactive",
          "finance_setup_limit"
        ],
        "title": "Availability",
        "type": "string"
      }
    },
    "required": [
      "setup_id",
      "kind",
      "version",
      "revision_id",
      "review_sha256",
      "state",
      "target",
      "label",
      "usable_locally",
      "availability"
    ],
    "title": "Summary",
    "type": "object",
    "x-no-null": false
  }
} as const;

export type AccountProposal = { "setup_id": string; "expected_version": number; "idempotency_key": string; "installation_id": string; "installation_sha256": string; "label": string; "permissions": Permissions };
export type AccountReview = { "kind": "account"; "setup_id": string; "revision_id": string; "revision": number; "installed": InstalledAccount; "label": string; "permissions": Permissions; "connection_version_id": string };
export type AccountTarget = { "kind": "account"; "installation_id": string };
export type Activation = { "setup_id": string; "expected_version": number; "revision_id": string; "review_sha256": string; "idempotency_key": string; "reviewed_account": true; "reviewed_environment": true; "reviewed_patient_customer"?: true; "confirm_local_activation": true };
export type Binding = { "setup_id": string; "expected_version": number; "revision_id": string; "review_sha256": string };
export type Bound = { "setup_id": string; "expected_version": number; "revision_id": string; "review_sha256": string; "idempotency_key": string };
export type Catalog = { "contract_version": 1; "scope": Scope; "enabled": boolean; "installed_accounts": Array<InstalledAccount>; "patients": Array<Patient>; "setups": Array<Summary> };
export type CustomerProposal = { "setup_id": string; "expected_version": number; "idempotency_key": string; "account": Binding; "patient_link_id": string; "customer_id": string; "label": string };
export type CustomerReview = { "kind": "customer"; "setup_id": string; "revision_id": string; "revision": number; "installed": InstalledAccount; "label": string; "account": Binding; "account_label": string; "connection_version_id": string; "customer_version_id": string; "patient": Patient; "customer_id": string };
export type CustomerTarget = { "kind": "customer"; "account_setup_id": string; "patient_link_id": string };
export type Detail = { "contract_version": 1; "scope": Scope; "summary": Summary; "review": AccountReview | CustomerReview; "last_receipt": Receipt };
export type Disable = { "setup_id": string; "expected_version": number; "revision_id": string; "review_sha256": string; "idempotency_key": string; "confirm_disable": true };
export type Effect = { "setup_id": string; "kind": "account" | "customer"; "version": number; "revision_id": string; "review_sha256": string; "state": "pending_review" | "active" | "disabled" | "revoked" };
export type History = { "contract_version": 1; "scope": Scope; "setup_id": string; "receipts": Array<Receipt> };
export type InstalledAccount = { "installation_id": string; "installation_sha256": string; "label": string; "environment": "sandbox" | "production"; "account_reference": string };
export type NotFound = { "contract_version": 1; "outcome": "not_found"; "scope": Scope; "command_kind": "propose_account" | "propose_customer" | "activate" | "disable" | "revoke"; "idempotency_key": string; "request_sha256": string };
export type Patient = { "patient_link_id": string; "label": string };
export type Permissions = { "read_status": boolean; "create_unconfirmed_intents": boolean };
export type Receipt = { "contract_version": 1; "outcome": "recorded"; "scope": Scope; "command_kind": "propose_account" | "propose_customer" | "activate" | "disable" | "revoke"; "idempotency_key": string; "request_sha256": string; "receipt_id": string; "recorded_at": string; "effect": Effect; "receipt_sha256": string };
export type Resolve = { "command_kind": "propose_account" | "propose_customer" | "activate" | "disable" | "revoke"; "idempotency_key": string; "request_sha256": string };
export type Revoke = { "setup_id": string; "expected_version": number; "revision_id": string; "review_sha256": string; "idempotency_key": string; "confirm_revoke": true };
export type Scope = { "box_id": string; "owner_id": string };
export type Summary = { "setup_id": string; "kind": "account" | "customer"; "version": number; "revision_id": string; "review_sha256": string; "state": "pending_review" | "active" | "disabled" | "revoked"; "target": AccountTarget | CustomerTarget; "label": string; "usable_locally": boolean; "availability": "available" | "finance_setup_disabled" | "finance_installation_changed" | "finance_account_changed" | "finance_patient_unavailable" | "finance_binding_unavailable" | "finance_setup_inactive" | "finance_setup_limit" };
export type FinanceSetupContractTypes = { AccountProposal: AccountProposal; AccountReview: AccountReview; AccountTarget: AccountTarget; Activation: Activation; Binding: Binding; Bound: Bound; Catalog: Catalog; CustomerProposal: CustomerProposal; CustomerReview: CustomerReview; CustomerTarget: CustomerTarget; Detail: Detail; Disable: Disable; Effect: Effect; History: History; InstalledAccount: InstalledAccount; NotFound: NotFound; Patient: Patient; Permissions: Permissions; Receipt: Receipt; Resolve: Resolve; Revoke: Revoke; Scope: Scope; Summary: Summary };
export type FinanceSetupContractName = keyof FinanceSetupContractTypes;
