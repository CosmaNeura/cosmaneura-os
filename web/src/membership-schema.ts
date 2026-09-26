// Generated from the existing public Python contract. Do not hand-edit shapes.
// Relational checks and exact commitments are in membership-contract.ts.
// Source SHA-256: 465e64f9c55a934b90a75f5fc5669ca56af9785efdb7adc1f61da85dc243d171
export const MEMBERSHIP_SCHEMAS = {
  "Bound": {
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
      "ticket_id",
      "expected_version",
      "revision_id",
      "payload_hash",
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
        "type": "integer",
        "x-rules": [
          "_version"
        ]
      },
      "scope": {
        "$ref": "#/$defs/Scope"
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
      "scope",
      "items"
    ],
    "title": "Catalog",
    "type": "object",
    "x-no-null": false
  },
  "Decision": {
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
      },
      "reviewed_patient": {
        "const": true,
        "title": "Reviewed Patient",
        "type": "boolean",
        "x-rules": [
          "_true"
        ]
      },
      "reviewed_local_only_authority": {
        "const": true,
        "title": "Reviewed Local Only Authority",
        "type": "boolean",
        "x-rules": [
          "_true"
        ]
      }
    },
    "required": [
      "ticket_id",
      "expected_version",
      "revision_id",
      "payload_hash",
      "idempotency_key",
      "review_sha256",
      "choice",
      "reviewed_patient",
      "reviewed_local_only_authority"
    ],
    "title": "Decision",
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
      "scope": {
        "$ref": "#/$defs/Scope"
      },
      "summary": {
        "$ref": "#/$defs/Summary"
      },
      "review": {
        "$ref": "#/$defs/Review"
      },
      "review_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Review Sha256",
        "type": "string"
      },
      "latest_result": {
        "anyOf": [
          {
            "$ref": "#/$defs/ResultView"
          },
          {
            "type": "null"
          }
        ]
      }
    },
    "required": [
      "contract_version",
      "scope",
      "summary",
      "review",
      "review_sha256",
      "latest_result"
    ],
    "title": "Detail",
    "type": "object",
    "x-no-null": false
  },
  "Document": {
    "additionalProperties": false,
    "properties": {
      "artifact_id": {
        "title": "Artifact Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Sha256",
        "type": "string"
      },
      "byte_length": {
        "maximum": 8388608,
        "minimum": 5,
        "title": "Byte Length",
        "type": "integer"
      },
      "media_type": {
        "const": "application/pdf",
        "title": "Media Type",
        "type": "string"
      }
    },
    "required": [
      "artifact_id",
      "sha256",
      "byte_length",
      "media_type"
    ],
    "title": "Document",
    "type": "object",
    "x-no-null": true
  },
  "Effect": {
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
      "payload_hash": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Payload Hash",
        "type": "string"
      },
      "version": {
        "maximum": 2147483647,
        "minimum": 1,
        "title": "Version",
        "type": "integer"
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
        "enum": [
          "proposed",
          "approved",
          "rejected",
          "result_recorded",
          "review_verified",
          "withdrawn"
        ],
        "title": "Effect",
        "type": "string"
      },
      "state": {
        "enum": [
          "pending_approval",
          "approved",
          "rejected",
          "closed",
          "withdrawn"
        ],
        "title": "State",
        "type": "string"
      },
      "evidence_classification": {
        "enum": [
          "local_unreconciled",
          "manual_ledger_record",
          "manual_ledger_and_finance_review"
        ],
        "title": "Evidence Classification",
        "type": "string"
      },
      "external_service_verified": {
        "const": false,
        "title": "External Service Verified",
        "type": "boolean"
      }
    },
    "required": [
      "ticket_id",
      "revision_id",
      "payload_hash",
      "version",
      "receipt_id",
      "recorded_at",
      "effect",
      "state",
      "evidence_classification",
      "external_service_verified"
    ],
    "title": "Effect",
    "type": "object",
    "x-no-null": true
  },
  "FinanceProof": {
    "additionalProperties": false,
    "properties": {
      "ticket_id": {
        "title": "Ticket Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "verification_receipt_id": {
        "title": "Verification Receipt Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "verification_receipt_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Verification Receipt Sha256",
        "type": "string"
      },
      "evidence_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Evidence Sha256",
        "type": "string"
      }
    },
    "required": [
      "ticket_id",
      "verification_receipt_id",
      "verification_receipt_sha256",
      "evidence_sha256"
    ],
    "title": "FinanceProof",
    "type": "object",
    "x-no-null": true
  },
  "History": {
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
        "$ref": "#/$defs/Scope"
      },
      "ticket_id": {
        "title": "Ticket Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "items": {
        "items": {
          "$ref": "#/$defs/HistoryItem"
        },
        "maxItems": 100,
        "title": "Items",
        "type": "array"
      }
    },
    "required": [
      "contract_version",
      "scope",
      "ticket_id",
      "items"
    ],
    "title": "History",
    "type": "object",
    "x-no-null": false
  },
  "HistoryItem": {
    "additionalProperties": false,
    "properties": {
      "request": {
        "anyOf": [
          {
            "$ref": "#/$defs/Proposal"
          },
          {
            "$ref": "#/$defs/Decision"
          },
          {
            "$ref": "#/$defs/Result"
          },
          {
            "$ref": "#/$defs/Verify"
          },
          {
            "$ref": "#/$defs/Withdraw"
          }
        ],
        "title": "Request"
      },
      "receipt": {
        "$ref": "#/$defs/Response"
      }
    },
    "required": [
      "request",
      "receipt"
    ],
    "title": "HistoryItem",
    "type": "object",
    "x-no-null": true
  },
  "LedgerProof": {
    "additionalProperties": false,
    "properties": {
      "source_label": {
        "maxLength": 80,
        "title": "Source Label",
        "type": "string",
        "x-rules": [
          "_text"
        ]
      },
      "system_kind": {
        "enum": [
          "hint",
          "atlas_md",
          "practice_owned_ledger",
          "other"
        ],
        "title": "System Kind",
        "type": "string"
      },
      "record_reference": {
        "pattern": "^[A-Za-z0-9:_-]{1,120}$",
        "title": "Record Reference",
        "type": "string"
      },
      "observed_at": {
        "title": "Observed At",
        "type": "string",
        "x-rules": [
          "_timestamp"
        ]
      },
      "document": {
        "$ref": "#/$defs/Document"
      },
      "observed_membership_state": {
        "enum": [
          "unknown",
          "not_enrolled",
          "pending_enrollment",
          "active",
          "paused",
          "ended"
        ],
        "title": "Observed Membership State",
        "type": "string"
      },
      "observed_billing_state": {
        "enum": [
          "unknown",
          "current",
          "past_due",
          "payment_failed"
        ],
        "title": "Observed Billing State",
        "type": "string"
      },
      "reviewed_record_matches_patient": {
        "const": true,
        "title": "Reviewed Record Matches Patient",
        "type": "boolean",
        "x-rules": [
          "_true"
        ]
      },
      "reviewed_document": {
        "const": true,
        "title": "Reviewed Document",
        "type": "boolean",
        "x-rules": [
          "_true"
        ]
      },
      "finance": {
        "anyOf": [
          {
            "$ref": "#/$defs/FinanceProof"
          },
          {
            "type": "null"
          }
        ],
        "default": null
      }
    },
    "required": [
      "source_label",
      "system_kind",
      "record_reference",
      "observed_at",
      "document",
      "observed_membership_state",
      "observed_billing_state",
      "reviewed_record_matches_patient",
      "reviewed_document"
    ],
    "title": "LedgerProof",
    "type": "object",
    "x-no-null": true
  },
  "MembershipRetire": {
    "additionalProperties": false,
    "properties": {
      "command_kind": {
        "enum": [
          "propose",
          "decide",
          "result",
          "verify",
          "withdraw"
        ],
        "title": "Command Kind",
        "type": "string"
      },
      "request": {
        "anyOf": [
          {
            "$ref": "#/$defs/Proposal"
          },
          {
            "$ref": "#/$defs/Decision"
          },
          {
            "$ref": "#/$defs/Result"
          },
          {
            "$ref": "#/$defs/Verify"
          },
          {
            "$ref": "#/$defs/Withdraw"
          }
        ],
        "title": "Request"
      },
      "request_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Request Sha256",
        "type": "string"
      }
    },
    "required": [
      "command_kind",
      "request",
      "request_sha256"
    ],
    "title": "MembershipRetire",
    "type": "object",
    "x-no-null": true
  },
  "MembershipRetirementRecord": {
    "additionalProperties": false,
    "properties": {
      "receipt_id": {
        "title": "Receipt Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "reason": {
        "enum": [
          "membership_source_changed",
          "membership_revision_changed",
          "membership_result_changed",
          "membership_exception_unresolved",
          "membership_evidence_changed",
          "membership_history_limit"
        ],
        "title": "Reason",
        "type": "string"
      },
      "retired_at": {
        "title": "Retired At",
        "type": "string",
        "x-rules": [
          "_timestamp"
        ]
      }
    },
    "required": [
      "receipt_id",
      "reason",
      "retired_at"
    ],
    "title": "MembershipRetirementRecord",
    "type": "object",
    "x-no-null": true
  },
  "MembershipRetirementResponse": {
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
        "$ref": "#/$defs/Scope"
      },
      "command_kind": {
        "enum": [
          "propose",
          "decide",
          "result",
          "verify",
          "withdraw"
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
        "const": "retired",
        "title": "Outcome",
        "type": "string"
      },
      "effect": {
        "title": "Effect",
        "type": "null"
      },
      "retirement": {
        "$ref": "#/$defs/MembershipRetirementRecord"
      },
      "receipt_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Receipt Sha256",
        "type": "string"
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
      "retirement",
      "receipt_sha256"
    ],
    "title": "MembershipRetirementResponse",
    "type": "object",
    "x-no-null": false
  },
  "Options": {
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
        "$ref": "#/$defs/Scope"
      },
      "patient_link_id": {
        "title": "Patient Link Id",
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
      "installed_membership_service": {
        "const": "not_selected",
        "title": "Installed Membership Service",
        "type": "string"
      }
    },
    "required": [
      "contract_version",
      "scope",
      "patient_link_id",
      "expected_workspace_revision",
      "source",
      "enabled",
      "installed_membership_service"
    ],
    "title": "Options",
    "type": "object",
    "x-no-null": false
  },
  "Proposal": {
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
      "source": {
        "$ref": "#/$defs/ReviewedSource"
      },
      "patient_link_id": {
        "title": "Patient Link Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "purpose": {
        "enum": [
          "enrollment_assistance",
          "membership_status_review",
          "failed_payment_follow_up"
        ],
        "title": "Purpose",
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
      "instructions": {
        "maxLength": 2000,
        "title": "Instructions",
        "type": "string",
        "x-rules": [
          "_text"
        ]
      }
    },
    "required": [
      "expected_workspace_revision",
      "idempotency_key",
      "source",
      "patient_link_id",
      "purpose",
      "due_date",
      "expected_outcome",
      "instructions"
    ],
    "title": "Proposal",
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
          "result",
          "verify",
          "withdraw"
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
      "contract_version": {
        "const": 1,
        "title": "Contract Version",
        "type": "integer",
        "x-rules": [
          "_version"
        ]
      },
      "scope": {
        "$ref": "#/$defs/Scope"
      },
      "command_kind": {
        "enum": [
          "propose",
          "decide",
          "result",
          "verify",
          "withdraw"
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
            "$ref": "#/$defs/Effect"
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
      "receipt_sha256"
    ],
    "title": "Response",
    "type": "object",
    "x-no-null": false
  },
  "Result": {
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
      },
      "idempotency_key": {
        "maxLength": 100,
        "minLength": 8,
        "pattern": "^[A-Za-z0-9:_-]+$",
        "title": "Idempotency Key",
        "type": "string"
      },
      "disposition": {
        "enum": [
          "local_preparation_ready",
          "record_reviewed",
          "needs_human"
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
      "ledger": {
        "anyOf": [
          {
            "$ref": "#/$defs/LedgerProof"
          },
          {
            "type": "null"
          }
        ],
        "default": null
      }
    },
    "required": [
      "ticket_id",
      "expected_version",
      "revision_id",
      "payload_hash",
      "idempotency_key",
      "disposition",
      "evidence"
    ],
    "title": "Result",
    "type": "object",
    "x-no-null": true
  },
  "ResultView": {
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
      "request": {
        "$ref": "#/$defs/Result"
      }
    },
    "required": [
      "receipt_id",
      "receipt_sha256",
      "request"
    ],
    "title": "ResultView",
    "type": "object",
    "x-no-null": true
  },
  "Review": {
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
      "patient_link_id": {
        "title": "Patient Link Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "proposal": {
        "$ref": "#/$defs/Proposal"
      },
      "authority": {
        "const": "local_human_review_only",
        "title": "Authority",
        "type": "string"
      },
      "automatic_membership_changes": {
        "const": false,
        "title": "Automatic Membership Changes",
        "type": "boolean"
      },
      "automatic_messages_or_money_movement": {
        "const": false,
        "title": "Automatic Messages Or Money Movement",
        "type": "boolean"
      }
    },
    "required": [
      "ticket_id",
      "revision_id",
      "patient_link_id",
      "proposal",
      "authority",
      "automatic_membership_changes",
      "automatic_messages_or_money_movement"
    ],
    "title": "Review",
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
      },
      "workspace_id": {
        "title": "Workspace Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      }
    },
    "required": [
      "box_id",
      "owner_id",
      "workspace_id"
    ],
    "title": "Scope",
    "type": "object",
    "x-no-null": true
  },
  "Summary": {
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
      "payload_hash": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Payload Hash",
        "type": "string"
      },
      "purpose": {
        "enum": [
          "enrollment_assistance",
          "membership_status_review",
          "failed_payment_follow_up"
        ],
        "title": "Purpose",
        "type": "string"
      },
      "due_date": {
        "title": "Due Date",
        "type": "string",
        "x-rules": [
          "_day"
        ]
      },
      "state": {
        "enum": [
          "pending_approval",
          "approved",
          "rejected",
          "closed",
          "withdrawn"
        ],
        "title": "State",
        "type": "string"
      },
      "evidence_classification": {
        "enum": [
          "local_unreconciled",
          "manual_ledger_record",
          "manual_ledger_and_finance_review"
        ],
        "title": "Evidence Classification",
        "type": "string"
      },
      "evidence_current": {
        "enum": [
          "none",
          "available",
          "changed"
        ],
        "title": "Evidence Current",
        "type": "string"
      },
      "result": {
        "enum": [
          "none",
          "local_preparation_ready",
          "record_reviewed",
          "needs_human"
        ],
        "title": "Result",
        "type": "string"
      },
      "verification": {
        "enum": [
          "pending",
          "review_verified"
        ],
        "title": "Verification",
        "type": "string"
      },
      "external_service_verified": {
        "const": false,
        "title": "External Service Verified",
        "type": "boolean"
      },
      "membership_authority": {
        "const": "not_established",
        "title": "Membership Authority",
        "type": "string"
      },
      "source_current": {
        "title": "Source Current",
        "type": "boolean"
      },
      "can_verify": {
        "title": "Can Verify",
        "type": "boolean"
      }
    },
    "required": [
      "ticket_id",
      "version",
      "revision_id",
      "payload_hash",
      "purpose",
      "due_date",
      "state",
      "evidence_classification",
      "evidence_current",
      "result",
      "verification",
      "external_service_verified",
      "membership_authority",
      "source_current",
      "can_verify"
    ],
    "title": "Summary",
    "type": "object",
    "x-no-null": true
  },
  "Verify": {
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
      "evidence_classification": {
        "enum": [
          "local_unreconciled",
          "manual_ledger_record",
          "manual_ledger_and_finance_review"
        ],
        "title": "Evidence Classification",
        "type": "string"
      },
      "reviewed_patient": {
        "const": true,
        "title": "Reviewed Patient",
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
      "reviewed_evidence_limits": {
        "const": true,
        "title": "Reviewed Evidence Limits",
        "type": "boolean",
        "x-rules": [
          "_true"
        ]
      },
      "confirm_review_completion": {
        "const": true,
        "title": "Confirm Review Completion",
        "type": "boolean",
        "x-rules": [
          "_true"
        ]
      }
    },
    "required": [
      "ticket_id",
      "expected_version",
      "revision_id",
      "payload_hash",
      "idempotency_key",
      "result_receipt_id",
      "result_receipt_sha256",
      "evidence_classification",
      "reviewed_patient",
      "reviewed_result",
      "reviewed_evidence_limits",
      "confirm_review_completion"
    ],
    "title": "Verify",
    "type": "object",
    "x-no-null": true
  },
  "Withdraw": {
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
      },
      "idempotency_key": {
        "maxLength": 100,
        "minLength": 8,
        "pattern": "^[A-Za-z0-9:_-]+$",
        "title": "Idempotency Key",
        "type": "string"
      },
      "confirm_withdraw": {
        "const": true,
        "title": "Confirm Withdraw",
        "type": "boolean",
        "x-rules": [
          "_true"
        ]
      }
    },
    "required": [
      "ticket_id",
      "expected_version",
      "revision_id",
      "payload_hash",
      "idempotency_key",
      "confirm_withdraw"
    ],
    "title": "Withdraw",
    "type": "object",
    "x-no-null": true
  }
} as const;

export type Bound = { "ticket_id": string; "expected_version": number; "revision_id": string; "payload_hash": string; "idempotency_key": string };
export type Catalog = { "contract_version": 1; "scope": Scope; "items": Array<Summary> };
export type Decision = { "ticket_id": string; "expected_version": number; "revision_id": string; "payload_hash": string; "idempotency_key": string; "review_sha256": string; "choice": "approve" | "reject"; "reviewed_patient": true; "reviewed_local_only_authority": true };
export type Detail = { "contract_version": 1; "scope": Scope; "summary": Summary; "review": Review; "review_sha256": string; "latest_result": ResultView | null };
export type Document = { "artifact_id": string; "sha256": string; "byte_length": number; "media_type": "application/pdf" };
export type Effect = { "ticket_id": string; "revision_id": string; "payload_hash": string; "version": number; "receipt_id": string; "recorded_at": string; "effect": "proposed" | "approved" | "rejected" | "result_recorded" | "review_verified" | "withdrawn"; "state": "pending_approval" | "approved" | "rejected" | "closed" | "withdrawn"; "evidence_classification": "local_unreconciled" | "manual_ledger_record" | "manual_ledger_and_finance_review"; "external_service_verified": false };
export type FinanceProof = { "ticket_id": string; "verification_receipt_id": string; "verification_receipt_sha256": string; "evidence_sha256": string };
export type History = { "contract_version": 1; "scope": Scope; "ticket_id": string; "items": Array<HistoryItem> };
export type HistoryItem = { "request": Proposal | Decision | Result | Verify | Withdraw; "receipt": Response };
export type LedgerProof = { "source_label": string; "system_kind": "hint" | "atlas_md" | "practice_owned_ledger" | "other"; "record_reference": string; "observed_at": string; "document": Document; "observed_membership_state": "unknown" | "not_enrolled" | "pending_enrollment" | "active" | "paused" | "ended"; "observed_billing_state": "unknown" | "current" | "past_due" | "payment_failed"; "reviewed_record_matches_patient": true; "reviewed_document": true; "finance"?: FinanceProof };
export type MembershipRetire = { "command_kind": "propose" | "decide" | "result" | "verify" | "withdraw"; "request": Proposal | Decision | Result | Verify | Withdraw; "request_sha256": string };
export type MembershipRetirementRecord = { "receipt_id": string; "reason": "membership_source_changed" | "membership_revision_changed" | "membership_result_changed" | "membership_exception_unresolved" | "membership_evidence_changed" | "membership_history_limit"; "retired_at": string };
export type MembershipRetirementResponse = { "contract_version": 1; "scope": Scope; "command_kind": "propose" | "decide" | "result" | "verify" | "withdraw"; "idempotency_key": string; "request_sha256": string; "outcome": "retired"; "effect": null; "retirement": MembershipRetirementRecord; "receipt_sha256": string };
export type Options = { "contract_version": 1; "scope": Scope; "patient_link_id": string; "expected_workspace_revision": number; "source": ReviewedSource | null; "enabled": boolean; "installed_membership_service": "not_selected" };
export type Proposal = { "expected_workspace_revision": number; "idempotency_key": string; "source": ReviewedSource; "patient_link_id": string; "purpose": "enrollment_assistance" | "membership_status_review" | "failed_payment_follow_up"; "due_date": string; "expected_outcome": string; "instructions": string };
export type Resolve = { "command_kind": "propose" | "decide" | "result" | "verify" | "withdraw"; "idempotency_key": string; "request_sha256": string };
export type Response = { "contract_version": 1; "scope": Scope; "command_kind": "propose" | "decide" | "result" | "verify" | "withdraw"; "idempotency_key": string; "request_sha256": string; "outcome": "recorded" | "not_found"; "effect": Effect | null; "receipt_sha256": string | null };
export type Result = { "ticket_id": string; "expected_version": number; "revision_id": string; "payload_hash": string; "idempotency_key": string; "disposition": "local_preparation_ready" | "record_reviewed" | "needs_human"; "evidence": string; "ledger"?: LedgerProof };
export type ResultView = { "receipt_id": string; "receipt_sha256": string; "request": Result };
export type Review = { "ticket_id": string; "revision_id": string; "patient_link_id": string; "proposal": Proposal; "authority": "local_human_review_only"; "automatic_membership_changes": false; "automatic_messages_or_money_movement": false };
export type ReviewedSource = { "kind": "reviewed_note"; "note_id": string; "content_sha256": string; "source_fingerprint": string };
export type Scope = { "box_id": string; "owner_id": string; "workspace_id": string };
export type Summary = { "ticket_id": string; "version": number; "revision_id": string; "payload_hash": string; "purpose": "enrollment_assistance" | "membership_status_review" | "failed_payment_follow_up"; "due_date": string; "state": "pending_approval" | "approved" | "rejected" | "closed" | "withdrawn"; "evidence_classification": "local_unreconciled" | "manual_ledger_record" | "manual_ledger_and_finance_review"; "evidence_current": "none" | "available" | "changed"; "result": "none" | "local_preparation_ready" | "record_reviewed" | "needs_human"; "verification": "pending" | "review_verified"; "external_service_verified": false; "membership_authority": "not_established"; "source_current": boolean; "can_verify": boolean };
export type Verify = { "ticket_id": string; "expected_version": number; "revision_id": string; "payload_hash": string; "idempotency_key": string; "result_receipt_id": string; "result_receipt_sha256": string; "evidence_classification": "local_unreconciled" | "manual_ledger_record" | "manual_ledger_and_finance_review"; "reviewed_patient": true; "reviewed_result": true; "reviewed_evidence_limits": true; "confirm_review_completion": true };
export type Withdraw = { "ticket_id": string; "expected_version": number; "revision_id": string; "payload_hash": string; "idempotency_key": string; "confirm_withdraw": true };
export type MembershipContractTypes = { Bound: Bound; Catalog: Catalog; Decision: Decision; Detail: Detail; Document: Document; Effect: Effect; FinanceProof: FinanceProof; History: History; HistoryItem: HistoryItem; LedgerProof: LedgerProof; MembershipRetire: MembershipRetire; MembershipRetirementRecord: MembershipRetirementRecord; MembershipRetirementResponse: MembershipRetirementResponse; Options: Options; Proposal: Proposal; Resolve: Resolve; Response: Response; Result: Result; ResultView: ResultView; Review: Review; ReviewedSource: ReviewedSource; Scope: Scope; Summary: Summary; Verify: Verify; Withdraw: Withdraw };
export type MembershipContractName = keyof MembershipContractTypes;
