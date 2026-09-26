// Generated from frozen R9 Pydantic contracts; do not hand-edit shapes.
// inbox_handoff_schemas.py SHA-256: 23b99faa9bfaaf1ad0ca395404772ddb114d9427bb1012b4037bb8b76270c3e5
export const INBOX_HANDOFF_SCHEMAS = {
  "Bound": {
    "additionalProperties": false,
    "properties": {
      "expected_version": {
        "maximum": 2147483647,
        "minimum": 1,
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
      "payload_hash": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Payload Hash",
        "type": "string"
      },
      "revision_id": {
        "title": "Revision Id",
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
      }
    },
    "required": [
      "idempotency_key",
      "ticket_id",
      "expected_version",
      "revision_id",
      "payload_hash"
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
        "type": "integer",
        "x-rules": [
          "_version"
        ]
      },
      "items": {
        "items": {
          "$ref": "#/$defs/Summary"
        },
        "maxItems": 100,
        "title": "Items",
        "type": "array"
      }
    },
    "required": [
      "contract_version",
      "items"
    ],
    "title": "Catalog",
    "type": "object",
    "x-no-null": false
  },
  "Decide": {
    "additionalProperties": false,
    "properties": {
      "choice": {
        "enum": [
          "approve",
          "reject"
        ],
        "title": "Choice",
        "type": "string"
      },
      "expected_version": {
        "maximum": 2147483647,
        "minimum": 1,
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
      "payload_hash": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Payload Hash",
        "type": "string"
      },
      "publish_selected_context": {
        "const": true,
        "title": "Publish Selected Context",
        "type": "boolean",
        "x-rules": [
          "_true"
        ]
      },
      "revision_id": {
        "title": "Revision Id",
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
      }
    },
    "required": [
      "idempotency_key",
      "ticket_id",
      "expected_version",
      "revision_id",
      "payload_hash",
      "choice",
      "publish_selected_context"
    ],
    "title": "Decide",
    "type": "object",
    "x-no-null": true
  },
  "Detail": {
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
      "due_date": {
        "anyOf": [
          {
            "type": "string",
            "x-rules": [
              "_day"
            ]
          },
          {
            "type": "null"
          }
        ],
        "title": "Due Date"
      },
      "expected_outcome": {
        "anyOf": [
          {
            "maxLength": 500,
            "type": "string",
            "x-rules": [
              "_text"
            ]
          },
          {
            "type": "null"
          }
        ],
        "title": "Expected Outcome"
      },
      "external_action_performed": {
        "const": false,
        "title": "External Action Performed",
        "type": "boolean"
      },
      "handoffs": {
        "items": {
          "$ref": "#/$defs/Responsibility"
        },
        "maxItems": 201,
        "title": "Handoffs",
        "type": "array"
      },
      "instructions": {
        "anyOf": [
          {
            "maxLength": 4000,
            "type": "string",
            "x-rules": [
              "_text"
            ]
          },
          {
            "type": "null"
          }
        ],
        "title": "Instructions"
      },
      "originator_available": {
        "title": "Originator Available",
        "type": "boolean"
      },
      "originator_id": {
        "title": "Originator Id",
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
      "private_source": {
        "anyOf": [
          {
            "$ref": "#/$defs/PrivateSource"
          },
          {
            "type": "null"
          }
        ],
        "default": null
      },
      "publication_active": {
        "title": "Publication Active",
        "type": "boolean"
      },
      "publication_receipt_id": {
        "anyOf": [
          {
            "type": "string",
            "x-rules": [
              "_uuid"
            ]
          },
          {
            "type": "null"
          }
        ],
        "title": "Publication Receipt Id"
      },
      "requires_owner_attention": {
        "title": "Requires Owner Attention",
        "type": "boolean"
      },
      "responsible_id": {
        "title": "Responsible Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "result": {
        "anyOf": [
          {
            "$ref": "#/$defs/SavedResult"
          },
          {
            "type": "null"
          }
        ]
      },
      "revision_id": {
        "title": "Revision Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "selected_context": {
        "anyOf": [
          {
            "maxLength": 2000,
            "type": "string",
            "x-rules": [
              "_text"
            ]
          },
          {
            "type": "null"
          }
        ],
        "title": "Selected Context"
      },
      "state": {
        "enum": [
          "pending_approval",
          "approved",
          "closed",
          "rejected",
          "source_unavailable"
        ],
        "title": "State",
        "type": "string"
      },
      "ticket_id": {
        "title": "Ticket Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "verified_current": {
        "title": "Verified Current",
        "type": "boolean"
      },
      "version": {
        "maximum": 2147483647,
        "minimum": 1,
        "title": "Version",
        "type": "integer"
      },
      "work_kind": {
        "const": "incoming_message",
        "title": "Work Kind",
        "type": "string"
      }
    },
    "required": [
      "contract_version",
      "work_kind",
      "ticket_id",
      "version",
      "revision_id",
      "payload_hash",
      "state",
      "publication_active",
      "requires_owner_attention",
      "originator_id",
      "originator_available",
      "responsible_id",
      "publication_receipt_id",
      "verified_current",
      "external_action_performed",
      "instructions",
      "selected_context",
      "due_date",
      "expected_outcome",
      "result",
      "handoffs"
    ],
    "title": "Detail",
    "type": "object",
    "x-no-null": false
  },
  "Effect": {
    "additionalProperties": false,
    "properties": {
      "effect_id": {
        "title": "Effect Id",
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
      "revision_id": {
        "title": "Revision Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "state": {
        "enum": [
          "pending_approval",
          "approved",
          "closed",
          "rejected"
        ],
        "title": "State",
        "type": "string"
      },
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
      }
    },
    "required": [
      "ticket_id",
      "version",
      "revision_id",
      "payload_hash",
      "effect_id",
      "state"
    ],
    "title": "Effect",
    "type": "object",
    "x-no-null": false
  },
  "Handoff": {
    "additionalProperties": false,
    "properties": {
      "expected_version": {
        "maximum": 2147483647,
        "minimum": 1,
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
      "kind": {
        "enum": [
          "offer",
          "accept",
          "decline",
          "recall",
          "reclaim"
        ],
        "title": "Kind",
        "type": "string"
      },
      "offer_id": {
        "anyOf": [
          {
            "type": "string",
            "x-rules": [
              "_uuid"
            ]
          },
          {
            "type": "null"
          }
        ],
        "default": null,
        "title": "Offer Id"
      },
      "payload_hash": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Payload Hash",
        "type": "string"
      },
      "recipient_id": {
        "anyOf": [
          {
            "type": "string",
            "x-rules": [
              "_uuid"
            ]
          },
          {
            "type": "null"
          }
        ],
        "default": null,
        "title": "Recipient Id"
      },
      "revision_id": {
        "title": "Revision Id",
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
      }
    },
    "required": [
      "idempotency_key",
      "ticket_id",
      "expected_version",
      "revision_id",
      "payload_hash",
      "kind"
    ],
    "title": "Handoff",
    "type": "object",
    "x-no-null": true
  },
  "PrivateSource": {
    "additionalProperties": false,
    "properties": {
      "item_id": {
        "title": "Item Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "review_receipt_id": {
        "title": "Review Receipt Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "review_receipt_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Review Receipt Sha256",
        "type": "string"
      },
      "source_id": {
        "title": "Source Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "source_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Source Sha256",
        "type": "string"
      },
      "unavailability": {
        "anyOf": [
          {
            "enum": [
              "feature_disabled",
              "source_changed",
              "review_changed",
              "authority_changed",
              "work_changed",
              "publication_required",
              "result_already_recorded",
              "responsibility_required",
              "responsibility_changed",
              "result_changed"
            ],
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Unavailability"
      }
    },
    "required": [
      "item_id",
      "source_id",
      "source_sha256",
      "review_receipt_id",
      "review_receipt_sha256",
      "unavailability"
    ],
    "title": "PrivateSource",
    "type": "object",
    "x-no-null": false
  },
  "Propose": {
    "additionalProperties": false,
    "properties": {
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
      "instructions": {
        "maxLength": 4000,
        "title": "Instructions",
        "type": "string",
        "x-rules": [
          "_text"
        ]
      },
      "item_id": {
        "title": "Item Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "review_receipt_id": {
        "title": "Review Receipt Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "review_receipt_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Review Receipt Sha256",
        "type": "string"
      },
      "reviewed_minimum_context": {
        "const": true,
        "title": "Reviewed Minimum Context",
        "type": "boolean",
        "x-rules": [
          "_true"
        ]
      },
      "selected_context": {
        "anyOf": [
          {
            "maxLength": 2000,
            "type": "string",
            "x-rules": [
              "_text"
            ]
          },
          {
            "type": "null"
          }
        ],
        "default": null,
        "title": "Selected Context"
      },
      "source_id": {
        "title": "Source Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "source_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Source Sha256",
        "type": "string"
      }
    },
    "required": [
      "idempotency_key",
      "item_id",
      "source_id",
      "source_sha256",
      "review_receipt_id",
      "review_receipt_sha256",
      "expected_workspace_revision",
      "instructions",
      "due_date",
      "expected_outcome",
      "reviewed_minimum_context"
    ],
    "title": "Propose",
    "type": "object",
    "x-no-null": true
  },
  "Resolve": {
    "additionalProperties": false,
    "properties": {
      "command_kind": {
        "enum": [
          "propose",
          "decide",
          "handoff",
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
    "title": "Resolve",
    "type": "object",
    "x-no-null": true
  },
  "Response": {
    "additionalProperties": false,
    "properties": {
      "command_kind": {
        "enum": [
          "propose",
          "decide",
          "handoff",
          "result",
          "verify"
        ],
        "title": "Command Kind",
        "type": "string"
      },
      "contract_version": {
        "const": 1,
        "title": "Contract Version",
        "type": "integer",
        "x-rules": [
          "_version"
        ]
      },
      "effect": {
        "anyOf": [
          {
            "$ref": "#/$defs/Effect"
          },
          {
            "type": "null"
          }
        ]
      },
      "idempotency_key": {
        "maxLength": 100,
        "minLength": 8,
        "pattern": "^[A-Za-z0-9:_-]+$",
        "title": "Idempotency Key",
        "type": "string"
      },
      "outcome": {
        "enum": [
          "recorded",
          "rejected"
        ],
        "title": "Outcome",
        "type": "string"
      },
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
      "recorded_at": {
        "title": "Recorded At",
        "type": "string",
        "x-rules": [
          "_timestamp"
        ]
      },
      "rejection": {
        "anyOf": [
          {
            "enum": [
              "feature_disabled",
              "source_changed",
              "review_changed",
              "authority_changed",
              "work_changed",
              "publication_required",
              "result_already_recorded",
              "responsibility_required",
              "responsibility_changed",
              "result_changed"
            ],
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Rejection"
      },
      "request_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Request Sha256",
        "type": "string"
      },
      "scope": {
        "$ref": "#/$defs/Scope"
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
      "rejection",
      "receipt_id",
      "recorded_at",
      "receipt_sha256"
    ],
    "title": "Response",
    "type": "object",
    "x-no-null": false
  },
  "Responsibility": {
    "additionalProperties": false,
    "properties": {
      "from_id": {
        "title": "From Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "id": {
        "title": "Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "kind": {
        "enum": [
          "offer",
          "accept",
          "decline",
          "recall",
          "reclaim"
        ],
        "title": "Kind",
        "type": "string"
      },
      "offer_id": {
        "anyOf": [
          {
            "type": "string",
            "x-rules": [
              "_uuid"
            ]
          },
          {
            "type": "null"
          }
        ],
        "title": "Offer Id"
      },
      "to_id": {
        "title": "To Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      }
    },
    "required": [
      "id",
      "kind",
      "from_id",
      "to_id",
      "offer_id"
    ],
    "title": "Responsibility",
    "type": "object",
    "x-no-null": false
  },
  "Result": {
    "additionalProperties": false,
    "properties": {
      "evidence": {
        "maxLength": 2000,
        "title": "Evidence",
        "type": "string",
        "x-rules": [
          "_text"
        ]
      },
      "expected_version": {
        "maximum": 2147483647,
        "minimum": 1,
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
      "no_external_action_claimed": {
        "const": true,
        "title": "No External Action Claimed",
        "type": "boolean",
        "x-rules": [
          "_true"
        ]
      },
      "payload_hash": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Payload Hash",
        "type": "string"
      },
      "revision_id": {
        "title": "Revision Id",
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
      }
    },
    "required": [
      "idempotency_key",
      "ticket_id",
      "expected_version",
      "revision_id",
      "payload_hash",
      "evidence",
      "no_external_action_claimed"
    ],
    "title": "Result",
    "type": "object",
    "x-no-null": true
  },
  "SavedResult": {
    "additionalProperties": false,
    "properties": {
      "actor_id": {
        "title": "Actor Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "evidence": {
        "maxLength": 2000,
        "title": "Evidence",
        "type": "string",
        "x-rules": [
          "_text"
        ]
      },
      "receipt_id": {
        "title": "Receipt Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "request_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Request Sha256",
        "type": "string"
      }
    },
    "required": [
      "receipt_id",
      "request_sha256",
      "actor_id",
      "evidence"
    ],
    "title": "SavedResult",
    "type": "object",
    "x-no-null": false
  },
  "Scope": {
    "additionalProperties": false,
    "properties": {
      "actor_id": {
        "title": "Actor Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "box_id": {
        "title": "Box Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "id": {
        "title": "Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "kind": {
        "enum": [
          "workspace",
          "ticket"
        ],
        "title": "Kind",
        "type": "string"
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
      "owner_id",
      "actor_id",
      "kind",
      "id"
    ],
    "title": "Scope",
    "type": "object",
    "x-no-null": false
  },
  "Summary": {
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
      "external_action_performed": {
        "const": false,
        "title": "External Action Performed",
        "type": "boolean"
      },
      "originator_available": {
        "title": "Originator Available",
        "type": "boolean"
      },
      "originator_id": {
        "title": "Originator Id",
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
      "publication_active": {
        "title": "Publication Active",
        "type": "boolean"
      },
      "publication_receipt_id": {
        "anyOf": [
          {
            "type": "string",
            "x-rules": [
              "_uuid"
            ]
          },
          {
            "type": "null"
          }
        ],
        "title": "Publication Receipt Id"
      },
      "requires_owner_attention": {
        "title": "Requires Owner Attention",
        "type": "boolean"
      },
      "responsible_id": {
        "title": "Responsible Id",
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
      "state": {
        "enum": [
          "pending_approval",
          "approved",
          "closed",
          "rejected",
          "source_unavailable"
        ],
        "title": "State",
        "type": "string"
      },
      "ticket_id": {
        "title": "Ticket Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "verified_current": {
        "title": "Verified Current",
        "type": "boolean"
      },
      "version": {
        "maximum": 2147483647,
        "minimum": 1,
        "title": "Version",
        "type": "integer"
      },
      "work_kind": {
        "const": "incoming_message",
        "title": "Work Kind",
        "type": "string"
      }
    },
    "required": [
      "contract_version",
      "work_kind",
      "ticket_id",
      "version",
      "revision_id",
      "payload_hash",
      "state",
      "publication_active",
      "requires_owner_attention",
      "originator_id",
      "originator_available",
      "responsible_id",
      "publication_receipt_id",
      "verified_current",
      "external_action_performed"
    ],
    "title": "Summary",
    "type": "object",
    "x-no-null": false
  },
  "Verify": {
    "additionalProperties": false,
    "properties": {
      "expected_version": {
        "maximum": 2147483647,
        "minimum": 1,
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
      "local_handoff_only": {
        "const": true,
        "title": "Local Handoff Only",
        "type": "boolean",
        "x-rules": [
          "_true"
        ]
      },
      "payload_hash": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Payload Hash",
        "type": "string"
      },
      "result_receipt_id": {
        "title": "Result Receipt Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "result_request_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Result Request Sha256",
        "type": "string"
      },
      "reviewed_current_source": {
        "const": true,
        "title": "Reviewed Current Source",
        "type": "boolean",
        "x-rules": [
          "_true"
        ]
      },
      "reviewed_result": {
        "const": true,
        "title": "Reviewed Result",
        "type": "boolean",
        "x-rules": [
          "_true"
        ]
      },
      "revision_id": {
        "title": "Revision Id",
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
      }
    },
    "required": [
      "idempotency_key",
      "ticket_id",
      "expected_version",
      "revision_id",
      "payload_hash",
      "result_receipt_id",
      "result_request_sha256",
      "reviewed_current_source",
      "reviewed_result",
      "local_handoff_only"
    ],
    "title": "Verify",
    "type": "object",
    "x-no-null": true
  }
} as const;

export type Bound = { "idempotency_key": string; "ticket_id": string; "expected_version": number; "revision_id": string; "payload_hash": string };
export type Catalog = { "contract_version": 1; "items": Array<Summary> };
export type Decide = { "idempotency_key": string; "ticket_id": string; "expected_version": number; "revision_id": string; "payload_hash": string; "choice": "approve" | "reject"; "publish_selected_context": true };
export type Detail = { "contract_version": 1; "work_kind": "incoming_message"; "ticket_id": string; "version": number; "revision_id": string; "payload_hash": string; "state": "pending_approval" | "approved" | "closed" | "rejected" | "source_unavailable"; "publication_active": boolean; "requires_owner_attention": boolean; "originator_id": string; "originator_available": boolean; "responsible_id": string; "publication_receipt_id": string | null; "verified_current": boolean; "external_action_performed": false; "instructions": string | null; "selected_context": string | null; "due_date": string | null; "expected_outcome": string | null; "result": SavedResult | null; "handoffs": Array<Responsibility>; "private_source"?: PrivateSource | null };
export type Effect = { "ticket_id": string; "version": number; "revision_id": string; "payload_hash": string; "effect_id": string; "state": "pending_approval" | "approved" | "closed" | "rejected" };
export type Handoff = { "idempotency_key": string; "ticket_id": string; "expected_version": number; "revision_id": string; "payload_hash": string; "kind": "offer" | "accept" | "decline" | "recall" | "reclaim"; "recipient_id"?: string; "offer_id"?: string };
export type PrivateSource = { "item_id": string; "source_id": string; "source_sha256": string; "review_receipt_id": string; "review_receipt_sha256": string; "unavailability": "feature_disabled" | "source_changed" | "review_changed" | "authority_changed" | "work_changed" | "publication_required" | "result_already_recorded" | "responsibility_required" | "responsibility_changed" | "result_changed" | null };
export type Propose = { "idempotency_key": string; "item_id": string; "source_id": string; "source_sha256": string; "review_receipt_id": string; "review_receipt_sha256": string; "expected_workspace_revision": number; "instructions": string; "selected_context"?: string; "due_date": string; "expected_outcome": string; "reviewed_minimum_context": true };
export type Resolve = { "command_kind": "propose" | "decide" | "handoff" | "result" | "verify"; "idempotency_key": string; "request_sha256": string };
export type Response = { "contract_version": 1; "scope": Scope; "command_kind": "propose" | "decide" | "handoff" | "result" | "verify"; "idempotency_key": string; "request_sha256": string; "outcome": "recorded" | "rejected"; "effect": Effect | null; "rejection": "feature_disabled" | "source_changed" | "review_changed" | "authority_changed" | "work_changed" | "publication_required" | "result_already_recorded" | "responsibility_required" | "responsibility_changed" | "result_changed" | null; "receipt_id": string; "recorded_at": string; "receipt_sha256": string };
export type Responsibility = { "id": string; "kind": "offer" | "accept" | "decline" | "recall" | "reclaim"; "from_id": string; "to_id": string; "offer_id": string | null };
export type Result = { "idempotency_key": string; "ticket_id": string; "expected_version": number; "revision_id": string; "payload_hash": string; "evidence": string; "no_external_action_claimed": true };
export type SavedResult = { "receipt_id": string; "request_sha256": string; "actor_id": string; "evidence": string };
export type Scope = { "box_id": string; "owner_id": string; "actor_id": string; "kind": "workspace" | "ticket"; "id": string };
export type Summary = { "contract_version": 1; "work_kind": "incoming_message"; "ticket_id": string; "version": number; "revision_id": string; "payload_hash": string; "state": "pending_approval" | "approved" | "closed" | "rejected" | "source_unavailable"; "publication_active": boolean; "requires_owner_attention": boolean; "originator_id": string; "originator_available": boolean; "responsible_id": string; "publication_receipt_id": string | null; "verified_current": boolean; "external_action_performed": false };
export type Verify = { "idempotency_key": string; "ticket_id": string; "expected_version": number; "revision_id": string; "payload_hash": string; "result_receipt_id": string; "result_request_sha256": string; "reviewed_current_source": true; "reviewed_result": true; "local_handoff_only": true };
export type InboxHandoffContractTypes = { Bound: Bound; Catalog: Catalog; Decide: Decide; Detail: Detail; Effect: Effect; Handoff: Handoff; PrivateSource: PrivateSource; Propose: Propose; Resolve: Resolve; Response: Response; Responsibility: Responsibility; Result: Result; SavedResult: SavedResult; Scope: Scope; Summary: Summary; Verify: Verify };
export type InboxHandoffContractName = keyof InboxHandoffContractTypes;
export type NotFound = {contract_version:1;outcome:"not_found";effect:null;scope:null} & Resolve;
export type Recorded = Omit<Response,"outcome"|"effect"|"rejection"> & {outcome:"recorded";effect:Effect;rejection:null};
export type Rejected = Omit<Response,"outcome"|"effect"|"rejection"> & {outcome:"rejected";effect:null;rejection:Exclude<Response["rejection"],null>};
export type InboxHandoffResponse = Recorded | Rejected;
export type InboxHandoffReceipt = InboxHandoffResponse | NotFound;
