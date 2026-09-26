// Generated from the existing public Python contract. Do not hand-edit shapes.
// Relational checks and exact commitments are in finance-contract.ts.
// Source SHA-256: 76b8bc1df4891d14b81a8f11df25545bd88ce9264da811b0e787e56d3e2f802b
export const FINANCE_SCHEMAS = {
  "BoundCommand": {
    "additionalProperties": false,
    "properties": {
      "expected_version": {
        "maximum": 2147483647,
        "minimum": 1,
        "title": "Expected Version",
        "type": "integer"
      },
      "operation_id": {
        "title": "Operation Id",
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
      "payload_hash": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Payload Hash",
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
      "expected_version",
      "operation_id",
      "revision_id",
      "payload_hash",
      "idempotency_key"
    ],
    "title": "BoundCommand",
    "type": "object",
    "x-no-null": true
  },
  "FinanceCatalog": {
    "additionalProperties": false,
    "properties": {
      "contract_version": {
        "const": 1,
        "title": "Contract Version",
        "type": "integer",
        "x-rules": [
          "_version"
        ]
      },
      "workspace_id": {
        "title": "Workspace Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "items": {
        "items": {
          "$ref": "#/$defs/FinanceSummary"
        },
        "maxItems": 25,
        "title": "Items",
        "type": "array"
      },
      "next_cursor": {
        "anyOf": [
          {
            "maxLength": 512,
            "minLength": 1,
            "pattern": "^[A-Za-z0-9_-]+\\.[a-f0-9]{64}$",
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Next Cursor"
      }
    },
    "required": [
      "contract_version",
      "workspace_id",
      "items",
      "next_cursor"
    ],
    "title": "FinanceCatalog",
    "type": "object",
    "x-no-null": false
  },
  "FinanceConnectionView": {
    "additionalProperties": false,
    "properties": {
      "id": {
        "title": "Id",
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
      "environment": {
        "enum": [
          "production",
          "sandbox"
        ],
        "title": "Environment",
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
      "availability": {
        "enum": [
          "enabled",
          "read_only",
          "unavailable"
        ],
        "title": "Availability",
        "type": "string"
      },
      "public_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Public Sha256",
        "type": "string"
      }
    },
    "required": [
      "id",
      "revision",
      "environment",
      "label",
      "availability",
      "public_sha256"
    ],
    "title": "FinanceConnectionView",
    "type": "object",
    "x-no-null": true
  },
  "FinanceCreation": {
    "additionalProperties": false,
    "properties": {
      "id": {
        "title": "Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "sequence": {
        "maximum": 2147483647,
        "minimum": 1,
        "title": "Sequence",
        "type": "integer"
      },
      "operation_id": {
        "title": "Operation Id",
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
      "sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Sha256",
        "type": "string"
      },
      "kind": {
        "const": "creation",
        "title": "Kind",
        "type": "string"
      },
      "acceptance": {
        "enum": [
          "accepted",
          "rejected",
          "unconfirmed"
        ],
        "title": "Acceptance",
        "type": "string"
      },
      "safe_error": {
        "anyOf": [
          {
            "enum": [
              "connector_disabled",
              "capability_unavailable",
              "connection_changed",
              "authority_required",
              "approval_changed",
              "request_invalid",
              "artifact_changed",
              "response_invalid",
              "response_too_large",
              "transport_unconfirmed",
              "provider_rejected",
              "provider_throttled",
              "duplicate_unresolved",
              "signature_invalid",
              "event_untrusted",
              "reference_unavailable"
            ],
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "default": null,
        "title": "Safe Error"
      }
    },
    "required": [
      "id",
      "sequence",
      "operation_id",
      "recorded_at",
      "sha256",
      "kind",
      "acceptance"
    ],
    "title": "FinanceCreation",
    "type": "object",
    "x-no-null": true
  },
  "FinanceCustomerView": {
    "additionalProperties": false,
    "properties": {
      "id": {
        "title": "Id",
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
      "connection_id": {
        "title": "Connection Id",
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
      },
      "availability": {
        "enum": [
          "reviewed",
          "unavailable"
        ],
        "title": "Availability",
        "type": "string"
      },
      "public_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Public Sha256",
        "type": "string"
      }
    },
    "required": [
      "id",
      "revision",
      "connection_id",
      "label",
      "availability",
      "public_sha256"
    ],
    "title": "FinanceCustomerView",
    "type": "object",
    "x-no-null": true
  },
  "FinanceDecision": {
    "additionalProperties": false,
    "properties": {
      "expected_version": {
        "maximum": 2147483647,
        "minimum": 1,
        "title": "Expected Version",
        "type": "integer"
      },
      "operation_id": {
        "title": "Operation Id",
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
      "payload_hash": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Payload Hash",
        "type": "string"
      },
      "idempotency_key": {
        "maxLength": 100,
        "minLength": 8,
        "pattern": "^[A-Za-z0-9:_-]+$",
        "title": "Idempotency Key",
        "type": "string"
      },
      "review_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Review Sha256",
        "type": "string"
      },
      "choice": {
        "enum": [
          "approve",
          "reject"
        ],
        "title": "Choice",
        "type": "string"
      }
    },
    "required": [
      "expected_version",
      "operation_id",
      "revision_id",
      "payload_hash",
      "idempotency_key",
      "review_sha256",
      "choice"
    ],
    "title": "FinanceDecision",
    "type": "object",
    "x-no-null": true
  },
  "FinanceDetail": {
    "additionalProperties": false,
    "properties": {
      "contract_version": {
        "const": 1,
        "title": "Contract Version",
        "type": "integer",
        "x-rules": [
          "_version"
        ]
      },
      "workspace_id": {
        "title": "Workspace Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "summary": {
        "$ref": "#/$defs/FinanceSummary"
      },
      "review": {
        "$ref": "#/$defs/FinanceReview"
      },
      "review_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Review Sha256",
        "type": "string"
      },
      "latest_result": {
        "anyOf": [
          {
            "$ref": "#/$defs/FinanceHumanResult"
          },
          {
            "type": "null"
          }
        ]
      }
    },
    "required": [
      "contract_version",
      "workspace_id",
      "summary",
      "review",
      "review_sha256",
      "latest_result"
    ],
    "title": "FinanceDetail",
    "type": "object",
    "x-no-null": false
  },
  "FinanceDispatch": {
    "additionalProperties": false,
    "properties": {
      "id": {
        "title": "Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "sequence": {
        "maximum": 2147483647,
        "minimum": 1,
        "title": "Sequence",
        "type": "integer"
      },
      "operation_id": {
        "title": "Operation Id",
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
      "sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Sha256",
        "type": "string"
      },
      "kind": {
        "const": "dispatch",
        "title": "Kind",
        "type": "string"
      },
      "dispatch": {
        "enum": [
          "invocation_started",
          "proved_not_dispatched",
          "unconfirmed"
        ],
        "title": "Dispatch",
        "type": "string"
      },
      "safe_error": {
        "anyOf": [
          {
            "enum": [
              "connector_disabled",
              "capability_unavailable",
              "connection_changed",
              "authority_required",
              "approval_changed",
              "request_invalid",
              "artifact_changed",
              "response_invalid",
              "response_too_large",
              "transport_unconfirmed",
              "provider_rejected",
              "provider_throttled",
              "duplicate_unresolved",
              "signature_invalid",
              "event_untrusted",
              "reference_unavailable"
            ],
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "default": null,
        "title": "Safe Error"
      }
    },
    "required": [
      "id",
      "sequence",
      "operation_id",
      "recorded_at",
      "sha256",
      "kind",
      "dispatch"
    ],
    "title": "FinanceDispatch",
    "type": "object",
    "x-no-null": true
  },
  "FinanceEffect": {
    "additionalProperties": false,
    "properties": {
      "ticket_id": {
        "title": "Ticket Id",
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
      "operation_id": {
        "title": "Operation Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "payload_hash": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Payload Hash",
        "type": "string"
      },
      "receipt_id": {
        "title": "Receipt Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "effect_version": {
        "maximum": 2147483647,
        "minimum": 1,
        "title": "Effect Version",
        "type": "integer"
      },
      "recorded_at": {
        "title": "Recorded At",
        "type": "string",
        "x-rules": [
          "_timestamp"
        ]
      },
      "effect": {
        "enum": [
          "proposed",
          "approved",
          "rejected",
          "withdrawn",
          "submit_claimed",
          "read_claimed",
          "result_recorded",
          "verified"
        ],
        "title": "Effect",
        "type": "string"
      }
    },
    "required": [
      "ticket_id",
      "revision_id",
      "operation_id",
      "payload_hash",
      "receipt_id",
      "effect_version",
      "recorded_at",
      "effect"
    ],
    "title": "FinanceEffect",
    "type": "object",
    "x-no-null": true
  },
  "FinanceHumanResult": {
    "additionalProperties": false,
    "properties": {
      "receipt_id": {
        "title": "Receipt Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "receipt_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Receipt Sha256",
        "type": "string"
      },
      "disposition": {
        "enum": [
          "reported_paid",
          "reported_unpaid",
          "verified_in_processor",
          "unable_to_establish"
        ],
        "title": "Disposition",
        "type": "string"
      },
      "evidence": {
        "maxLength": 2000,
        "title": "Evidence",
        "type": "string",
        "x-rules": [
          "_text"
        ]
      },
      "observation_head": {
        "$ref": "#/$defs/ObservationHead"
      },
      "recorded_at": {
        "title": "Recorded At",
        "type": "string",
        "x-rules": [
          "_timestamp"
        ]
      }
    },
    "required": [
      "receipt_id",
      "receipt_sha256",
      "disposition",
      "evidence",
      "observation_head",
      "recorded_at"
    ],
    "title": "FinanceHumanResult",
    "type": "object",
    "x-no-null": true
  },
  "FinanceObservationBase": {
    "additionalProperties": false,
    "properties": {
      "id": {
        "title": "Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "sequence": {
        "maximum": 2147483647,
        "minimum": 1,
        "title": "Sequence",
        "type": "integer"
      },
      "operation_id": {
        "title": "Operation Id",
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
      "sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Sha256",
        "type": "string"
      }
    },
    "required": [
      "id",
      "sequence",
      "operation_id",
      "recorded_at",
      "sha256"
    ],
    "title": "FinanceObservationBase",
    "type": "object",
    "x-no-null": true
  },
  "FinanceObservations": {
    "additionalProperties": false,
    "properties": {
      "contract_version": {
        "const": 1,
        "title": "Contract Version",
        "type": "integer",
        "x-rules": [
          "_version"
        ]
      },
      "workspace_id": {
        "title": "Workspace Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "ticket_id": {
        "title": "Ticket Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "operation_id": {
        "title": "Operation Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "observations": {
        "items": {
          "discriminator": {
            "mapping": {
              "creation": "#/$defs/FinanceCreation",
              "dispatch": "#/$defs/FinanceDispatch",
              "payment": "#/$defs/FinancePayment"
            },
            "propertyName": "kind"
          },
          "oneOf": [
            {
              "$ref": "#/$defs/FinanceDispatch"
            },
            {
              "$ref": "#/$defs/FinanceCreation"
            },
            {
              "$ref": "#/$defs/FinancePayment"
            }
          ]
        },
        "maxItems": 20,
        "title": "Observations",
        "type": "array"
      },
      "observation_head": {
        "$ref": "#/$defs/ObservationHead"
      },
      "next_cursor": {
        "anyOf": [
          {
            "maxLength": 512,
            "minLength": 1,
            "pattern": "^[A-Za-z0-9_-]+\\.[a-f0-9]{64}$",
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Next Cursor"
      }
    },
    "required": [
      "contract_version",
      "workspace_id",
      "ticket_id",
      "operation_id",
      "observations",
      "observation_head",
      "next_cursor"
    ],
    "title": "FinanceObservations",
    "type": "object",
    "x-no-null": false
  },
  "FinanceOptions": {
    "additionalProperties": false,
    "properties": {
      "contract_version": {
        "const": 1,
        "title": "Contract Version",
        "type": "integer",
        "x-rules": [
          "_version"
        ]
      },
      "workspace_id": {
        "title": "Workspace Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "expected_workspace_revision": {
        "maximum": 2147483647,
        "minimum": 1,
        "title": "Expected Workspace Revision",
        "type": "integer"
      },
      "source": {
        "anyOf": [
          {
            "$ref": "#/$defs/ReviewedSource"
          },
          {
            "type": "null"
          }
        ]
      },
      "enabled": {
        "title": "Enabled",
        "type": "boolean"
      },
      "connections": {
        "items": {
          "$ref": "#/$defs/FinanceConnectionView"
        },
        "maxItems": 50,
        "title": "Connections",
        "type": "array"
      },
      "customers": {
        "items": {
          "$ref": "#/$defs/FinanceCustomerView"
        },
        "maxItems": 50,
        "title": "Customers",
        "type": "array"
      }
    },
    "required": [
      "contract_version",
      "workspace_id",
      "expected_workspace_revision",
      "source",
      "enabled",
      "connections",
      "customers"
    ],
    "title": "FinanceOptions",
    "type": "object",
    "x-no-null": false
  },
  "FinancePayment": {
    "additionalProperties": false,
    "properties": {
      "id": {
        "title": "Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "sequence": {
        "maximum": 2147483647,
        "minimum": 1,
        "title": "Sequence",
        "type": "integer"
      },
      "operation_id": {
        "title": "Operation Id",
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
      "sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Sha256",
        "type": "string"
      },
      "kind": {
        "const": "payment",
        "title": "Kind",
        "type": "string"
      },
      "payment_state": {
        "enum": [
          "not_observed",
          "requires_payment_method",
          "requires_confirmation",
          "requires_action",
          "processing",
          "requires_capture",
          "canceled",
          "succeeded",
          "unknown"
        ],
        "title": "Payment State",
        "type": "string"
      },
      "amount": {
        "maximum": 99999999,
        "minimum": 50,
        "title": "Amount",
        "type": "integer"
      },
      "currency": {
        "const": "usd",
        "title": "Currency",
        "type": "string"
      },
      "amount_received": {
        "maximum": 99999999,
        "minimum": 0,
        "title": "Amount Received",
        "type": "integer"
      },
      "livemode": {
        "anyOf": [
          {
            "type": "boolean"
          },
          {
            "type": "null"
          }
        ],
        "default": null,
        "title": "Livemode"
      },
      "safe_error": {
        "anyOf": [
          {
            "enum": [
              "connector_disabled",
              "capability_unavailable",
              "connection_changed",
              "authority_required",
              "approval_changed",
              "request_invalid",
              "artifact_changed",
              "response_invalid",
              "response_too_large",
              "transport_unconfirmed",
              "provider_rejected",
              "provider_throttled",
              "duplicate_unresolved",
              "signature_invalid",
              "event_untrusted",
              "reference_unavailable"
            ],
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "default": null,
        "title": "Safe Error"
      }
    },
    "required": [
      "id",
      "sequence",
      "operation_id",
      "recorded_at",
      "sha256",
      "kind",
      "payment_state",
      "amount",
      "currency",
      "amount_received"
    ],
    "title": "FinancePayment",
    "type": "object",
    "x-no-null": true
  },
  "FinanceProposal": {
    "additionalProperties": false,
    "properties": {
      "expected_workspace_revision": {
        "maximum": 2147483647,
        "minimum": 1,
        "title": "Expected Workspace Revision",
        "type": "integer"
      },
      "idempotency_key": {
        "maxLength": 100,
        "minLength": 8,
        "pattern": "^[A-Za-z0-9:_-]+$",
        "title": "Idempotency Key",
        "type": "string"
      },
      "proposed_operation_id": {
        "title": "Proposed Operation Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "source": {
        "$ref": "#/$defs/ReviewedSource"
      },
      "connection": {
        "$ref": "#/$defs/Selection"
      },
      "customer": {
        "$ref": "#/$defs/Selection"
      },
      "amount": {
        "maximum": 99999999,
        "minimum": 50,
        "title": "Amount",
        "type": "integer"
      },
      "currency": {
        "const": "usd",
        "title": "Currency",
        "type": "string"
      },
      "due_date": {
        "title": "Due Date",
        "type": "string",
        "x-rules": [
          "_day"
        ]
      },
      "expected_outcome": {
        "maxLength": 500,
        "title": "Expected Outcome",
        "type": "string",
        "x-rules": [
          "_text"
        ]
      },
      "revises": {
        "anyOf": [
          {
            "$ref": "#/$defs/Revision"
          },
          {
            "type": "null"
          }
        ],
        "default": null
      }
    },
    "required": [
      "expected_workspace_revision",
      "idempotency_key",
      "proposed_operation_id",
      "source",
      "connection",
      "customer",
      "amount",
      "currency",
      "due_date",
      "expected_outcome"
    ],
    "title": "FinanceProposal",
    "type": "object",
    "x-no-null": true
  },
  "FinanceResolve": {
    "additionalProperties": false,
    "properties": {
      "command_kind": {
        "enum": [
          "propose",
          "decide",
          "withdraw",
          "submit",
          "reconcile",
          "result",
          "verify"
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
    "title": "FinanceResolve",
    "type": "object",
    "x-no-null": true
  },
  "FinanceResponse": {
    "additionalProperties": false,
    "properties": {
      "contract_version": {
        "const": 1,
        "title": "Contract Version",
        "type": "integer",
        "x-rules": [
          "_version"
        ]
      },
      "scope": {
        "$ref": "#/$defs/FinanceScope"
      },
      "command_kind": {
        "enum": [
          "propose",
          "decide",
          "withdraw",
          "submit",
          "reconcile",
          "result",
          "verify"
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
      "outcome": {
        "enum": [
          "recorded",
          "not_found"
        ],
        "title": "Outcome",
        "type": "string"
      },
      "effect": {
        "anyOf": [
          {
            "$ref": "#/$defs/FinanceEffect"
          },
          {
            "type": "null"
          }
        ]
      },
      "receipt_sha256": {
        "anyOf": [
          {
            "pattern": "^[a-f0-9]{64}$",
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Receipt Sha256"
      },
      "observed_at": {
        "title": "Observed At",
        "type": "string",
        "x-rules": [
          "_timestamp"
        ]
      }
    },
    "required": [
      "contract_version",
      "scope",
      "command_kind",
      "idempotency_key",
      "request_sha256",
      "outcome",
      "effect",
      "receipt_sha256",
      "observed_at"
    ],
    "title": "FinanceResponse",
    "type": "object",
    "x-no-null": false
  },
  "FinanceResult": {
    "additionalProperties": false,
    "properties": {
      "expected_version": {
        "maximum": 2147483647,
        "minimum": 1,
        "title": "Expected Version",
        "type": "integer"
      },
      "operation_id": {
        "title": "Operation Id",
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
      "payload_hash": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Payload Hash",
        "type": "string"
      },
      "idempotency_key": {
        "maxLength": 100,
        "minLength": 8,
        "pattern": "^[A-Za-z0-9:_-]+$",
        "title": "Idempotency Key",
        "type": "string"
      },
      "observation_head": {
        "$ref": "#/$defs/ObservationHead"
      },
      "evidence_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Evidence Sha256",
        "type": "string"
      },
      "disposition": {
        "enum": [
          "reported_paid",
          "reported_unpaid",
          "verified_in_processor",
          "unable_to_establish"
        ],
        "title": "Disposition",
        "type": "string"
      },
      "evidence": {
        "maxLength": 2000,
        "title": "Evidence",
        "type": "string",
        "x-rules": [
          "_text"
        ]
      }
    },
    "required": [
      "expected_version",
      "operation_id",
      "revision_id",
      "payload_hash",
      "idempotency_key",
      "observation_head",
      "evidence_sha256",
      "disposition",
      "evidence"
    ],
    "title": "FinanceResult",
    "type": "object",
    "x-no-null": true
  },
  "FinanceReview": {
    "additionalProperties": false,
    "properties": {
      "ticket_id": {
        "title": "Ticket Id",
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
      "operation_id": {
        "title": "Operation Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "connection": {
        "$ref": "#/$defs/FinanceConnectionView"
      },
      "customer": {
        "$ref": "#/$defs/FinanceCustomerView"
      },
      "source": {
        "$ref": "#/$defs/ReviewedSource"
      },
      "amount": {
        "maximum": 99999999,
        "minimum": 50,
        "title": "Amount",
        "type": "integer"
      },
      "currency": {
        "const": "usd",
        "title": "Currency",
        "type": "string"
      },
      "due_date": {
        "title": "Due Date",
        "type": "string",
        "x-rules": [
          "_day"
        ]
      },
      "expected_outcome": {
        "maxLength": 500,
        "title": "Expected Outcome",
        "type": "string",
        "x-rules": [
          "_text"
        ]
      },
      "expires_at": {
        "title": "Expires At",
        "type": "string",
        "x-rules": [
          "_timestamp"
        ]
      },
      "processor_confirmation": {
        "const": "not_requested",
        "title": "Processor Confirmation",
        "type": "string"
      }
    },
    "required": [
      "ticket_id",
      "revision_id",
      "operation_id",
      "connection",
      "customer",
      "source",
      "amount",
      "currency",
      "due_date",
      "expected_outcome",
      "expires_at",
      "processor_confirmation"
    ],
    "title": "FinanceReview",
    "type": "object",
    "x-no-null": true
  },
  "FinanceScope": {
    "additionalProperties": false,
    "properties": {
      "kind": {
        "const": "workspace",
        "title": "Kind",
        "type": "string"
      },
      "id": {
        "title": "Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      }
    },
    "required": [
      "kind",
      "id"
    ],
    "title": "FinanceScope",
    "type": "object",
    "x-no-null": true
  },
  "FinanceSummary": {
    "additionalProperties": false,
    "properties": {
      "ticket_id": {
        "title": "Ticket Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
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
      "operation_id": {
        "title": "Operation Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "payload_hash": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Payload Hash",
        "type": "string"
      },
      "state": {
        "enum": [
          "pending_approval",
          "approved",
          "rejected",
          "withdrawn",
          "superseded",
          "closed"
        ],
        "title": "State",
        "type": "string"
      },
      "amount": {
        "maximum": 99999999,
        "minimum": 50,
        "title": "Amount",
        "type": "integer"
      },
      "currency": {
        "const": "usd",
        "title": "Currency",
        "type": "string"
      },
      "creation": {
        "enum": [
          "not_observed",
          "accepted",
          "rejected",
          "unconfirmed"
        ],
        "title": "Creation",
        "type": "string"
      },
      "payment_state": {
        "enum": [
          "not_observed",
          "requires_payment_method",
          "requires_confirmation",
          "requires_action",
          "processing",
          "requires_capture",
          "canceled",
          "succeeded",
          "unknown"
        ],
        "title": "Payment State",
        "type": "string"
      },
      "amount_received": {
        "maximum": 99999999,
        "minimum": 0,
        "title": "Amount Received",
        "type": "integer"
      },
      "submit_claimed": {
        "title": "Submit Claimed",
        "type": "boolean"
      },
      "conflicting_evidence": {
        "title": "Conflicting Evidence",
        "type": "boolean"
      },
      "result": {
        "enum": [
          "none",
          "reported_paid",
          "reported_unpaid",
          "verified_in_processor",
          "unable_to_establish"
        ],
        "title": "Result",
        "type": "string"
      },
      "verification": {
        "enum": [
          "pending",
          "verified"
        ],
        "title": "Verification",
        "type": "string"
      },
      "observation_head": {
        "$ref": "#/$defs/ObservationHead"
      },
      "evidence_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Evidence Sha256",
        "type": "string"
      }
    },
    "required": [
      "ticket_id",
      "version",
      "revision_id",
      "operation_id",
      "payload_hash",
      "state",
      "amount",
      "currency",
      "creation",
      "payment_state",
      "amount_received",
      "submit_claimed",
      "conflicting_evidence",
      "result",
      "verification",
      "observation_head",
      "evidence_sha256"
    ],
    "title": "FinanceSummary",
    "type": "object",
    "x-no-null": true
  },
  "FinanceVerify": {
    "additionalProperties": false,
    "description": "Exact owner attestation fields; no payment confirm/capture instruction.",
    "properties": {
      "expected_version": {
        "maximum": 2147483647,
        "minimum": 1,
        "title": "Expected Version",
        "type": "integer"
      },
      "operation_id": {
        "title": "Operation Id",
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
      "payload_hash": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Payload Hash",
        "type": "string"
      },
      "idempotency_key": {
        "maxLength": 100,
        "minLength": 8,
        "pattern": "^[A-Za-z0-9:_-]+$",
        "title": "Idempotency Key",
        "type": "string"
      },
      "result_receipt_id": {
        "title": "Result Receipt Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "result_receipt_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Result Receipt Sha256",
        "type": "string"
      },
      "observation_head": {
        "$ref": "#/$defs/ObservationHead"
      },
      "evidence_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Evidence Sha256",
        "type": "string"
      },
      "reviewed_result": {
        "const": true,
        "title": "Reviewed Result",
        "type": "boolean",
        "x-rules": [
          "_true"
        ]
      },
      "reviewed_observations": {
        "const": true,
        "title": "Reviewed Observations",
        "type": "boolean",
        "x-rules": [
          "_true"
        ]
      },
      "outcome_confirmed": {
        "const": true,
        "title": "Outcome Confirmed",
        "type": "boolean",
        "x-rules": [
          "_true"
        ]
      },
      "reviewed_conflicting_evidence": {
        "title": "Reviewed Conflicting Evidence",
        "type": "boolean"
      }
    },
    "required": [
      "expected_version",
      "operation_id",
      "revision_id",
      "payload_hash",
      "idempotency_key",
      "result_receipt_id",
      "result_receipt_sha256",
      "observation_head",
      "evidence_sha256",
      "reviewed_result",
      "reviewed_observations",
      "outcome_confirmed",
      "reviewed_conflicting_evidence"
    ],
    "title": "FinanceVerify",
    "type": "object",
    "x-no-null": true
  },
  "ObservationHead": {
    "additionalProperties": false,
    "properties": {
      "sequence": {
        "maximum": 2147483647,
        "minimum": 0,
        "title": "Sequence",
        "type": "integer"
      },
      "sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Sha256",
        "type": "string"
      }
    },
    "required": [
      "sequence",
      "sha256"
    ],
    "title": "ObservationHead",
    "type": "object",
    "x-no-null": true
  },
  "ReviewedSource": {
    "additionalProperties": false,
    "properties": {
      "kind": {
        "const": "reviewed_note",
        "title": "Kind",
        "type": "string"
      },
      "note_id": {
        "title": "Note Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "content_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Content Sha256",
        "type": "string"
      },
      "source_fingerprint": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Source Fingerprint",
        "type": "string"
      }
    },
    "required": [
      "kind",
      "note_id",
      "content_sha256",
      "source_fingerprint"
    ],
    "title": "ReviewedSource",
    "type": "object",
    "x-no-null": true
  },
  "Revision": {
    "additionalProperties": false,
    "properties": {
      "ticket_id": {
        "title": "Ticket Id",
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
      "payload_hash": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Payload Hash",
        "type": "string"
      }
    },
    "required": [
      "ticket_id",
      "expected_version",
      "revision_id",
      "payload_hash"
    ],
    "title": "Revision",
    "type": "object",
    "x-no-null": true
  },
  "Selection": {
    "additionalProperties": false,
    "properties": {
      "id": {
        "title": "Id",
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
      "public_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Public Sha256",
        "type": "string"
      }
    },
    "required": [
      "id",
      "revision",
      "public_sha256"
    ],
    "title": "Selection",
    "type": "object",
    "x-no-null": true
  }
} as const;

export type BoundCommand = { "expected_version": number; "operation_id": string; "revision_id": string; "payload_hash": string; "idempotency_key": string };
export type FinanceCatalog = { "contract_version": 1; "workspace_id": string; "items": Array<FinanceSummary>; "next_cursor": string | null };
export type FinanceConnectionView = { "id": string; "revision": number; "environment": "production" | "sandbox"; "label": string; "availability": "enabled" | "read_only" | "unavailable"; "public_sha256": string };
export type FinanceCreation = { "id": string; "sequence": number; "operation_id": string; "recorded_at": string; "sha256": string; "kind": "creation"; "acceptance": "accepted" | "rejected" | "unconfirmed"; "safe_error"?: "connector_disabled" | "capability_unavailable" | "connection_changed" | "authority_required" | "approval_changed" | "request_invalid" | "artifact_changed" | "response_invalid" | "response_too_large" | "transport_unconfirmed" | "provider_rejected" | "provider_throttled" | "duplicate_unresolved" | "signature_invalid" | "event_untrusted" | "reference_unavailable" };
export type FinanceCustomerView = { "id": string; "revision": number; "connection_id": string; "label": string; "availability": "reviewed" | "unavailable"; "public_sha256": string };
export type FinanceDecision = { "expected_version": number; "operation_id": string; "revision_id": string; "payload_hash": string; "idempotency_key": string; "review_sha256": string; "choice": "approve" | "reject" };
export type FinanceDetail = { "contract_version": 1; "workspace_id": string; "summary": FinanceSummary; "review": FinanceReview; "review_sha256": string; "latest_result": FinanceHumanResult | null };
export type FinanceDispatch = { "id": string; "sequence": number; "operation_id": string; "recorded_at": string; "sha256": string; "kind": "dispatch"; "dispatch": "invocation_started" | "proved_not_dispatched" | "unconfirmed"; "safe_error"?: "connector_disabled" | "capability_unavailable" | "connection_changed" | "authority_required" | "approval_changed" | "request_invalid" | "artifact_changed" | "response_invalid" | "response_too_large" | "transport_unconfirmed" | "provider_rejected" | "provider_throttled" | "duplicate_unresolved" | "signature_invalid" | "event_untrusted" | "reference_unavailable" };
export type FinanceEffect = { "ticket_id": string; "revision_id": string; "operation_id": string; "payload_hash": string; "receipt_id": string; "effect_version": number; "recorded_at": string; "effect": "proposed" | "approved" | "rejected" | "withdrawn" | "submit_claimed" | "read_claimed" | "result_recorded" | "verified" };
export type FinanceHumanResult = { "receipt_id": string; "receipt_sha256": string; "disposition": "reported_paid" | "reported_unpaid" | "verified_in_processor" | "unable_to_establish"; "evidence": string; "observation_head": ObservationHead; "recorded_at": string };
export type FinanceObservationBase = { "id": string; "sequence": number; "operation_id": string; "recorded_at": string; "sha256": string };
export type FinanceObservations = { "contract_version": 1; "workspace_id": string; "ticket_id": string; "operation_id": string; "observations": Array<FinanceDispatch | FinanceCreation | FinancePayment>; "observation_head": ObservationHead; "next_cursor": string | null };
export type FinanceOptions = { "contract_version": 1; "workspace_id": string; "expected_workspace_revision": number; "source": ReviewedSource | null; "enabled": boolean; "connections": Array<FinanceConnectionView>; "customers": Array<FinanceCustomerView> };
export type FinancePayment = { "id": string; "sequence": number; "operation_id": string; "recorded_at": string; "sha256": string; "kind": "payment"; "payment_state": "not_observed" | "requires_payment_method" | "requires_confirmation" | "requires_action" | "processing" | "requires_capture" | "canceled" | "succeeded" | "unknown"; "amount": number; "currency": "usd"; "amount_received": number; "livemode"?: boolean; "safe_error"?: "connector_disabled" | "capability_unavailable" | "connection_changed" | "authority_required" | "approval_changed" | "request_invalid" | "artifact_changed" | "response_invalid" | "response_too_large" | "transport_unconfirmed" | "provider_rejected" | "provider_throttled" | "duplicate_unresolved" | "signature_invalid" | "event_untrusted" | "reference_unavailable" };
export type FinanceProposal = { "expected_workspace_revision": number; "idempotency_key": string; "proposed_operation_id": string; "source": ReviewedSource; "connection": Selection; "customer": Selection; "amount": number; "currency": "usd"; "due_date": string; "expected_outcome": string; "revises"?: Revision };
export type FinanceResolve = { "command_kind": "propose" | "decide" | "withdraw" | "submit" | "reconcile" | "result" | "verify"; "idempotency_key": string; "request_sha256": string };
export type FinanceResponse = { "contract_version": 1; "scope": FinanceScope; "command_kind": "propose" | "decide" | "withdraw" | "submit" | "reconcile" | "result" | "verify"; "idempotency_key": string; "request_sha256": string; "outcome": "recorded" | "not_found"; "effect": FinanceEffect | null; "receipt_sha256": string | null; "observed_at": string };
export type FinanceResult = { "expected_version": number; "operation_id": string; "revision_id": string; "payload_hash": string; "idempotency_key": string; "observation_head": ObservationHead; "evidence_sha256": string; "disposition": "reported_paid" | "reported_unpaid" | "verified_in_processor" | "unable_to_establish"; "evidence": string };
export type FinanceReview = { "ticket_id": string; "revision_id": string; "operation_id": string; "connection": FinanceConnectionView; "customer": FinanceCustomerView; "source": ReviewedSource; "amount": number; "currency": "usd"; "due_date": string; "expected_outcome": string; "expires_at": string; "processor_confirmation": "not_requested" };
export type FinanceScope = { "kind": "workspace"; "id": string };
export type FinanceSummary = { "ticket_id": string; "version": number; "revision_id": string; "operation_id": string; "payload_hash": string; "state": "pending_approval" | "approved" | "rejected" | "withdrawn" | "superseded" | "closed"; "amount": number; "currency": "usd"; "creation": "not_observed" | "accepted" | "rejected" | "unconfirmed"; "payment_state": "not_observed" | "requires_payment_method" | "requires_confirmation" | "requires_action" | "processing" | "requires_capture" | "canceled" | "succeeded" | "unknown"; "amount_received": number; "submit_claimed": boolean; "conflicting_evidence": boolean; "result": "none" | "reported_paid" | "reported_unpaid" | "verified_in_processor" | "unable_to_establish"; "verification": "pending" | "verified"; "observation_head": ObservationHead; "evidence_sha256": string };
export type FinanceVerify = { "expected_version": number; "operation_id": string; "revision_id": string; "payload_hash": string; "idempotency_key": string; "result_receipt_id": string; "result_receipt_sha256": string; "observation_head": ObservationHead; "evidence_sha256": string; "reviewed_result": true; "reviewed_observations": true; "outcome_confirmed": true; "reviewed_conflicting_evidence": boolean };
export type ObservationHead = { "sequence": number; "sha256": string };
export type ReviewedSource = { "kind": "reviewed_note"; "note_id": string; "content_sha256": string; "source_fingerprint": string };
export type Revision = { "ticket_id": string; "expected_version": number; "revision_id": string; "payload_hash": string };
export type Selection = { "id": string; "revision": number; "public_sha256": string };
export type FinanceContractTypes = { BoundCommand: BoundCommand; FinanceCatalog: FinanceCatalog; FinanceConnectionView: FinanceConnectionView; FinanceCreation: FinanceCreation; FinanceCustomerView: FinanceCustomerView; FinanceDecision: FinanceDecision; FinanceDetail: FinanceDetail; FinanceDispatch: FinanceDispatch; FinanceEffect: FinanceEffect; FinanceHumanResult: FinanceHumanResult; FinanceObservationBase: FinanceObservationBase; FinanceObservations: FinanceObservations; FinanceOptions: FinanceOptions; FinancePayment: FinancePayment; FinanceProposal: FinanceProposal; FinanceResolve: FinanceResolve; FinanceResponse: FinanceResponse; FinanceResult: FinanceResult; FinanceReview: FinanceReview; FinanceScope: FinanceScope; FinanceSummary: FinanceSummary; FinanceVerify: FinanceVerify; ObservationHead: ObservationHead; ReviewedSource: ReviewedSource; Revision: Revision; Selection: Selection };
export type FinanceContractName = keyof FinanceContractTypes;
