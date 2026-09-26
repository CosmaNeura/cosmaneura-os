// Generated from the current public Pydantic Inbox contracts; do not hand-edit shapes.
// inbox_work_schemas.py SHA-256: 8725829481ff382f2bd005ffa4acc260fed783d6a568b70c93364b3b2431e26d
// inbox_review_schemas.py SHA-256: 6ea544b09fcd55796ca98db496d6712b736c32edfa27df7dc879aa2df9d95d8b
export const INBOX_SCHEMAS = {
  "Availability": {
    "additionalProperties": false,
    "properties": {
      "review": {
        "title": "Review",
        "type": "boolean"
      },
      "triage": {
        "title": "Triage",
        "type": "boolean"
      },
      "result": {
        "title": "Result",
        "type": "boolean"
      },
      "verify": {
        "title": "Verify",
        "type": "boolean"
      },
      "history_capacity_remaining": {
        "maximum": 100,
        "minimum": 0,
        "title": "History Capacity Remaining",
        "type": "integer"
      }
    },
    "required": [
      "review",
      "triage",
      "result",
      "verify",
      "history_capacity_remaining"
    ],
    "title": "Availability",
    "type": "object",
    "x-no-null": false
  },
  "Bound": {
    "additionalProperties": false,
    "properties": {
      "item_id": {
        "title": "Item Id",
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
      "source_id": {
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
        "title": "Source Id"
      },
      "source_sha256": {
        "anyOf": [
          {
            "pattern": "^[a-f0-9]{64}$",
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "default": null,
        "title": "Source Sha256"
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
      "item_id",
      "expected_version",
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
      "enabled": {
        "title": "Enabled",
        "type": "boolean"
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
      "enabled",
      "items"
    ],
    "title": "Catalog",
    "type": "object",
    "x-no-null": false
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
      "source": {
        "anyOf": [
          {
            "$ref": "#/$defs/Source"
          },
          {
            "type": "null"
          }
        ]
      },
      "latest_review": {
        "anyOf": [
          {
            "$ref": "#/$defs/Receipt"
          },
          {
            "type": "null"
          }
        ]
      },
      "latest_triage": {
        "anyOf": [
          {
            "$ref": "#/$defs/Receipt"
          },
          {
            "type": "null"
          }
        ]
      },
      "latest_result": {
        "anyOf": [
          {
            "$ref": "#/$defs/Receipt"
          },
          {
            "type": "null"
          }
        ]
      },
      "latest_verification": {
        "anyOf": [
          {
            "$ref": "#/$defs/Receipt"
          },
          {
            "type": "null"
          }
        ]
      },
      "availability": {
        "$ref": "#/$defs/Availability"
      }
    },
    "required": [
      "contract_version",
      "scope",
      "summary",
      "source",
      "latest_review",
      "latest_triage",
      "latest_result",
      "latest_verification",
      "availability"
    ],
    "title": "Detail",
    "type": "object",
    "x-no-null": false
  },
  "Effect": {
    "additionalProperties": false,
    "properties": {
      "item_id": {
        "title": "Item Id",
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
      "source_id": {
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
        "title": "Source Id"
      },
      "source_sha256": {
        "anyOf": [
          {
            "pattern": "^[a-f0-9]{64}$",
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Source Sha256"
      },
      "state": {
        "enum": [
          "needs_review",
          "reviewed",
          "triaged",
          "result_recorded",
          "closed_local_review",
          "needs_human"
        ],
        "title": "State",
        "type": "string"
      }
    },
    "required": [
      "item_id",
      "version",
      "source_id",
      "source_sha256",
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
        "type": "integer",
        "x-rules": [
          "_version"
        ]
      },
      "scope": {
        "$ref": "#/$defs/Scope"
      },
      "item_id": {
        "title": "Item Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "sources": {
        "items": {
          "$ref": "#/$defs/SourceMetadata"
        },
        "maxItems": 50,
        "title": "Sources",
        "type": "array"
      },
      "reads": {
        "items": {
          "$ref": "#/$defs/ReadHistory"
        },
        "maxItems": 100,
        "title": "Reads",
        "type": "array"
      },
      "commands": {
        "items": {
          "$ref": "#/$defs/HistoryItem"
        },
        "maxItems": 100,
        "title": "Commands",
        "type": "array"
      }
    },
    "required": [
      "contract_version",
      "scope",
      "item_id",
      "sources",
      "reads",
      "commands"
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
            "$ref": "#/$defs/Review"
          },
          {
            "$ref": "#/$defs/Triage"
          },
          {
            "$ref": "#/$defs/Result"
          },
          {
            "$ref": "#/$defs/Verify"
          }
        ],
        "title": "Request"
      },
      "receipt": {
        "$ref": "#/$defs/Receipt"
      }
    },
    "required": [
      "request",
      "receipt"
    ],
    "title": "HistoryItem",
    "type": "object",
    "x-no-null": false
  },
  "ReadHistory": {
    "additionalProperties": false,
    "properties": {
      "id": {
        "title": "Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "item_id": {
        "title": "Item Id",
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
      "outcome": {
        "enum": [
          "new",
          "newer",
          "older",
          "same",
          "conflict",
          "failure"
        ],
        "title": "Outcome",
        "type": "string"
      },
      "source_id": {
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
        "title": "Source Id"
      },
      "source_sha256": {
        "anyOf": [
          {
            "pattern": "^[a-f0-9]{64}$",
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Source Sha256"
      },
      "safe_error": {
        "anyOf": [
          {
            "enum": [
              "authority_required",
              "reference_unavailable",
              "response_invalid",
              "response_too_large",
              "provider_throttled",
              "provider_unavailable",
              "request_timeout",
              "source_scope_changed"
            ],
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Safe Error"
      },
      "observed_at": {
        "anyOf": [
          {
            "type": "string",
            "x-rules": [
              "_timestamp"
            ]
          },
          {
            "type": "null"
          }
        ],
        "title": "Observed At"
      },
      "item_response_sha256": {
        "anyOf": [
          {
            "pattern": "^[a-f0-9]{64}$",
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Item Response Sha256"
      },
      "conversation_response_sha256": {
        "anyOf": [
          {
            "pattern": "^[a-f0-9]{64}$",
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Conversation Response Sha256"
      },
      "request_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Request Sha256",
        "type": "string"
      },
      "grant_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Grant Sha256",
        "type": "string"
      },
      "recorded_at": {
        "title": "Recorded At",
        "type": "string",
        "x-rules": [
          "_timestamp"
        ]
      },
      "receipt_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Receipt Sha256",
        "type": "string"
      }
    },
    "required": [
      "id",
      "item_id",
      "version",
      "outcome",
      "source_id",
      "source_sha256",
      "safe_error",
      "observed_at",
      "item_response_sha256",
      "conversation_response_sha256",
      "request_sha256",
      "grant_sha256",
      "recorded_at",
      "receipt_sha256"
    ],
    "title": "ReadHistory",
    "type": "object",
    "x-no-null": false
  },
  "Receipt": {
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
          "review",
          "triage",
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
          "rejected",
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
      "rejection": {
        "anyOf": [
          {
            "enum": [
              "inbox_version_changed",
              "inbox_source_changed",
              "inbox_binding_unavailable",
              "inbox_workspace_changed",
              "inbox_review_required",
              "inbox_triage_required",
              "inbox_result_changed",
              "inbox_exception_unresolved",
              "inbox_feature_disabled",
              "inbox_history_limit"
            ],
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Rejection"
      },
      "receipt_id": {
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
        "title": "Receipt Id"
      },
      "recorded_at": {
        "anyOf": [
          {
            "type": "string",
            "x-rules": [
              "_timestamp"
            ]
          },
          {
            "type": "null"
          }
        ],
        "title": "Recorded At"
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
      "rejection",
      "receipt_id",
      "recorded_at",
      "receipt_sha256"
    ],
    "title": "Receipt",
    "type": "object",
    "x-no-null": false
  },
  "Resolve": {
    "additionalProperties": false,
    "properties": {
      "item_id": {
        "title": "Item Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "command_kind": {
        "enum": [
          "review",
          "triage",
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
      "item_id",
      "command_kind",
      "idempotency_key",
      "request_sha256"
    ],
    "title": "Resolve",
    "type": "object",
    "x-no-null": true
  },
  "Result": {
    "additionalProperties": false,
    "properties": {
      "item_id": {
        "title": "Item Id",
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
      "source_id": {
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
        "title": "Source Id"
      },
      "source_sha256": {
        "anyOf": [
          {
            "pattern": "^[a-f0-9]{64}$",
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "default": null,
        "title": "Source Sha256"
      },
      "idempotency_key": {
        "maxLength": 100,
        "minLength": 8,
        "pattern": "^[A-Za-z0-9:_-]+$",
        "title": "Idempotency Key",
        "type": "string"
      },
      "triage_receipt_id": {
        "title": "Triage Receipt Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "triage_receipt_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Triage Receipt Sha256",
        "type": "string"
      },
      "disposition": {
        "enum": [
          "local_review_complete",
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
      "no_external_action_claimed": {
        "const": true,
        "title": "No External Action Claimed",
        "type": "boolean",
        "x-rules": [
          "_true"
        ]
      }
    },
    "required": [
      "item_id",
      "expected_version",
      "idempotency_key",
      "triage_receipt_id",
      "triage_receipt_sha256",
      "disposition",
      "evidence",
      "no_external_action_claimed"
    ],
    "title": "Result",
    "type": "object",
    "x-no-null": true
  },
  "Review": {
    "additionalProperties": false,
    "properties": {
      "item_id": {
        "title": "Item Id",
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
      "source_id": {
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
        "title": "Source Id"
      },
      "source_sha256": {
        "anyOf": [
          {
            "pattern": "^[a-f0-9]{64}$",
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "default": null,
        "title": "Source Sha256"
      },
      "idempotency_key": {
        "maxLength": 100,
        "minLength": 8,
        "pattern": "^[A-Za-z0-9:_-]+$",
        "title": "Idempotency Key",
        "type": "string"
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
      "patient_link_id": {
        "title": "Patient Link Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "reviewed_patient": {
        "const": true,
        "title": "Reviewed Patient",
        "type": "boolean",
        "x-rules": [
          "_true"
        ]
      },
      "reviewed_exact_thread": {
        "const": true,
        "title": "Reviewed Exact Thread",
        "type": "boolean",
        "x-rules": [
          "_true"
        ]
      },
      "reviewed_untrusted_source": {
        "const": true,
        "title": "Reviewed Untrusted Source",
        "type": "boolean",
        "x-rules": [
          "_true"
        ]
      }
    },
    "required": [
      "item_id",
      "expected_version",
      "idempotency_key",
      "workspace_id",
      "expected_workspace_revision",
      "patient_link_id",
      "reviewed_patient",
      "reviewed_exact_thread",
      "reviewed_untrusted_source"
    ],
    "title": "Review",
    "type": "object",
    "x-no-null": true
  },
  "ReviewOptions": {
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
      "item_id": {
        "title": "Item Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "item_version": {
        "maximum": 2147483647,
        "minimum": 1,
        "title": "Item Version",
        "type": "integer"
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
      "patient_link_id": {
        "title": "Patient Link Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "choices": {
        "items": {
          "$ref": "#/$defs/ReviewTarget"
        },
        "maxItems": 100,
        "title": "Choices",
        "type": "array"
      },
      "options_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Options Sha256",
        "type": "string"
      }
    },
    "required": [
      "contract_version",
      "scope",
      "item_id",
      "item_version",
      "source_id",
      "source_sha256",
      "patient_link_id",
      "choices",
      "options_sha256"
    ],
    "title": "ReviewOptions",
    "type": "object",
    "x-no-null": false
  },
  "ReviewTarget": {
    "additionalProperties": false,
    "properties": {
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
      "appointment_id": {
        "title": "Appointment Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "label": {
        "maxLength": 200,
        "minLength": 1,
        "title": "Label",
        "type": "string"
      },
      "start_at": {
        "title": "Start At",
        "type": "string",
        "x-rules": [
          "_timestamp"
        ]
      }
    },
    "required": [
      "workspace_id",
      "expected_workspace_revision",
      "appointment_id",
      "label",
      "start_at"
    ],
    "title": "ReviewTarget",
    "type": "object",
    "x-no-null": false
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
  "Source": {
    "additionalProperties": false,
    "properties": {
      "source_id": {
        "title": "Source Id",
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
      "source_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Source Sha256",
        "type": "string"
      },
      "created_at": {
        "title": "Created At",
        "type": "string",
        "x-rules": [
          "_timestamp"
        ]
      },
      "modified_at": {
        "title": "Modified At",
        "type": "string",
        "x-rules": [
          "_timestamp"
        ]
      },
      "observed_at": {
        "title": "Observed At",
        "type": "string",
        "x-rules": [
          "_timestamp"
        ]
      },
      "incomplete_content": {
        "title": "Incomplete Content",
        "type": "boolean"
      },
      "vendor": {
        "const": "spruce",
        "title": "Vendor",
        "type": "string"
      },
      "conversation_id": {
        "maxLength": 255,
        "title": "Conversation Id",
        "type": "string"
      },
      "item_reference": {
        "maxLength": 255,
        "title": "Item Reference",
        "type": "string"
      },
      "contact_id": {
        "maxLength": 255,
        "title": "Contact Id",
        "type": "string"
      },
      "patient_link_id": {
        "title": "Patient Link Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "correspondence_version_id": {
        "title": "Correspondence Version Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "correspondence_public_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Correspondence Public Sha256",
        "type": "string"
      },
      "text": {
        "maxLength": 16384,
        "title": "Text",
        "type": "string"
      },
      "attachments": {
        "title": "Attachments",
        "type": "boolean"
      },
      "attachment_types": {
        "items": {
          "enum": [
            "audio",
            "carePlan",
            "document",
            "entityProfile",
            "genericUrl",
            "image",
            "paymentRequest",
            "video",
            "visit",
            "unknown"
          ],
          "type": "string"
        },
        "maxItems": 10,
        "title": "Attachment Types",
        "type": "array"
      },
      "pages": {
        "title": "Pages",
        "type": "boolean"
      },
      "buttons": {
        "title": "Buttons",
        "type": "boolean"
      },
      "event": {
        "title": "Event",
        "type": "boolean"
      },
      "conversation_archived": {
        "title": "Conversation Archived",
        "type": "boolean"
      },
      "conversation_read_only": {
        "title": "Conversation Read Only",
        "type": "boolean"
      },
      "item_response_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Item Response Sha256",
        "type": "string"
      },
      "conversation_response_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Conversation Response Sha256",
        "type": "string"
      },
      "trust": {
        "const": "untrusted_external_text",
        "title": "Trust",
        "type": "string"
      },
      "projection_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Projection Sha256",
        "type": "string"
      }
    },
    "required": [
      "source_id",
      "sequence",
      "source_sha256",
      "created_at",
      "modified_at",
      "observed_at",
      "incomplete_content",
      "vendor",
      "conversation_id",
      "item_reference",
      "contact_id",
      "patient_link_id",
      "correspondence_version_id",
      "correspondence_public_sha256",
      "text",
      "attachments",
      "attachment_types",
      "pages",
      "buttons",
      "event",
      "conversation_archived",
      "conversation_read_only",
      "item_response_sha256",
      "conversation_response_sha256",
      "trust",
      "projection_sha256"
    ],
    "title": "Source",
    "type": "object",
    "x-no-null": false
  },
  "SourceMetadata": {
    "additionalProperties": false,
    "properties": {
      "source_id": {
        "title": "Source Id",
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
      "source_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Source Sha256",
        "type": "string"
      },
      "created_at": {
        "title": "Created At",
        "type": "string",
        "x-rules": [
          "_timestamp"
        ]
      },
      "modified_at": {
        "title": "Modified At",
        "type": "string",
        "x-rules": [
          "_timestamp"
        ]
      },
      "observed_at": {
        "title": "Observed At",
        "type": "string",
        "x-rules": [
          "_timestamp"
        ]
      },
      "incomplete_content": {
        "title": "Incomplete Content",
        "type": "boolean"
      }
    },
    "required": [
      "source_id",
      "sequence",
      "source_sha256",
      "created_at",
      "modified_at",
      "observed_at",
      "incomplete_content"
    ],
    "title": "SourceMetadata",
    "type": "object",
    "x-no-null": false
  },
  "Summary": {
    "additionalProperties": false,
    "properties": {
      "item_id": {
        "title": "Item Id",
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
      "label": {
        "maxLength": 80,
        "title": "Label",
        "type": "string"
      },
      "patient_link_id": {
        "title": "Patient Link Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "source_id": {
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
        "title": "Source Id"
      },
      "source_sha256": {
        "anyOf": [
          {
            "pattern": "^[a-f0-9]{64}$",
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Source Sha256"
      },
      "state": {
        "enum": [
          "needs_review",
          "reviewed",
          "triaged",
          "result_recorded",
          "closed_local_review",
          "needs_human"
        ],
        "title": "State",
        "type": "string"
      },
      "source_conflict": {
        "title": "Source Conflict",
        "type": "boolean"
      },
      "read_issue": {
        "anyOf": [
          {
            "enum": [
              "authority_required",
              "reference_unavailable",
              "response_invalid",
              "response_too_large",
              "provider_throttled",
              "provider_unavailable",
              "request_timeout",
              "source_scope_changed"
            ],
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Read Issue"
      },
      "binding_current": {
        "title": "Binding Current",
        "type": "boolean"
      },
      "incomplete_content": {
        "title": "Incomplete Content",
        "type": "boolean"
      },
      "workspace_id": {
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
        "title": "Workspace Id"
      },
      "workspace_current": {
        "title": "Workspace Current",
        "type": "boolean"
      },
      "classification": {
        "anyOf": [
          {
            "enum": [
              "administrative_review",
              "clinical_human_review",
              "urgent_human_review",
              "source_exception"
            ],
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Classification"
      },
      "human_review_required": {
        "const": true,
        "title": "Human Review Required",
        "type": "boolean"
      },
      "vendor_latest_state_verified": {
        "const": false,
        "title": "Vendor Latest State Verified",
        "type": "boolean"
      },
      "external_action_performed": {
        "const": false,
        "title": "External Action Performed",
        "type": "boolean"
      },
      "handoff_available": {
        "const": false,
        "title": "Handoff Available",
        "type": "boolean"
      }
    },
    "required": [
      "item_id",
      "version",
      "label",
      "patient_link_id",
      "source_id",
      "source_sha256",
      "state",
      "source_conflict",
      "read_issue",
      "binding_current",
      "incomplete_content",
      "workspace_id",
      "workspace_current",
      "classification",
      "human_review_required",
      "vendor_latest_state_verified",
      "external_action_performed",
      "handoff_available"
    ],
    "title": "Summary",
    "type": "object",
    "x-no-null": false
  },
  "Triage": {
    "additionalProperties": false,
    "properties": {
      "item_id": {
        "title": "Item Id",
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
      "source_id": {
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
        "title": "Source Id"
      },
      "source_sha256": {
        "anyOf": [
          {
            "pattern": "^[a-f0-9]{64}$",
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "default": null,
        "title": "Source Sha256"
      },
      "idempotency_key": {
        "maxLength": 100,
        "minLength": 8,
        "pattern": "^[A-Za-z0-9:_-]+$",
        "title": "Idempotency Key",
        "type": "string"
      },
      "classification": {
        "enum": [
          "administrative_review",
          "clinical_human_review",
          "urgent_human_review",
          "source_exception"
        ],
        "title": "Classification",
        "type": "string"
      },
      "due_date": {
        "title": "Due Date",
        "type": "string",
        "x-rules": [
          "_day"
        ]
      },
      "instructions": {
        "maxLength": 2000,
        "title": "Instructions",
        "type": "string",
        "x-rules": [
          "_text"
        ]
      },
      "human_disposition_required": {
        "const": true,
        "title": "Human Disposition Required",
        "type": "boolean",
        "x-rules": [
          "_true"
        ]
      }
    },
    "required": [
      "item_id",
      "expected_version",
      "idempotency_key",
      "classification",
      "due_date",
      "instructions",
      "human_disposition_required"
    ],
    "title": "Triage",
    "type": "object",
    "x-no-null": true
  },
  "Verify": {
    "additionalProperties": false,
    "properties": {
      "item_id": {
        "title": "Item Id",
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
      "source_id": {
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
        "title": "Source Id"
      },
      "source_sha256": {
        "anyOf": [
          {
            "pattern": "^[a-f0-9]{64}$",
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "default": null,
        "title": "Source Sha256"
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
      "reviewed_patient": {
        "const": true,
        "title": "Reviewed Patient",
        "type": "boolean",
        "x-rules": [
          "_true"
        ]
      },
      "reviewed_exact_source": {
        "const": true,
        "title": "Reviewed Exact Source",
        "type": "boolean",
        "x-rules": [
          "_true"
        ]
      },
      "reviewed_human_result": {
        "const": true,
        "title": "Reviewed Human Result",
        "type": "boolean",
        "x-rules": [
          "_true"
        ]
      },
      "confirm_local_review_only": {
        "const": true,
        "title": "Confirm Local Review Only",
        "type": "boolean",
        "x-rules": [
          "_true"
        ]
      }
    },
    "required": [
      "item_id",
      "expected_version",
      "idempotency_key",
      "result_receipt_id",
      "result_receipt_sha256",
      "reviewed_patient",
      "reviewed_exact_source",
      "reviewed_human_result",
      "confirm_local_review_only"
    ],
    "title": "Verify",
    "type": "object",
    "x-no-null": true
  }
} as const;

export type Availability = { "review": boolean; "triage": boolean; "result": boolean; "verify": boolean; "history_capacity_remaining": number };
export type Bound = { "item_id": string; "expected_version": number; "source_id"?: string; "source_sha256"?: string; "idempotency_key": string };
export type Catalog = { "contract_version": 1; "scope": Scope; "enabled": boolean; "items": Array<Summary> };
export type Detail = { "contract_version": 1; "scope": Scope; "summary": Summary; "source": Source | null; "latest_review": Receipt | null; "latest_triage": Receipt | null; "latest_result": Receipt | null; "latest_verification": Receipt | null; "availability": Availability };
export type Effect = { "item_id": string; "version": number; "source_id": string | null; "source_sha256": string | null; "state": "needs_review" | "reviewed" | "triaged" | "result_recorded" | "closed_local_review" | "needs_human" };
export type History = { "contract_version": 1; "scope": Scope; "item_id": string; "sources": Array<SourceMetadata>; "reads": Array<ReadHistory>; "commands": Array<HistoryItem> };
export type HistoryItem = { "request": Review | Triage | Result | Verify; "receipt": Receipt };
export type ReadHistory = { "id": string; "item_id": string; "version": number; "outcome": "new" | "newer" | "older" | "same" | "conflict" | "failure"; "source_id": string | null; "source_sha256": string | null; "safe_error": "authority_required" | "reference_unavailable" | "response_invalid" | "response_too_large" | "provider_throttled" | "provider_unavailable" | "request_timeout" | "source_scope_changed" | null; "observed_at": string | null; "item_response_sha256": string | null; "conversation_response_sha256": string | null; "request_sha256": string; "grant_sha256": string; "recorded_at": string; "receipt_sha256": string };
export type Receipt = { "contract_version": 1; "scope": Scope; "command_kind": "review" | "triage" | "result" | "verify"; "idempotency_key": string; "request_sha256": string; "outcome": "recorded" | "rejected" | "not_found"; "effect": Effect | null; "rejection": "inbox_version_changed" | "inbox_source_changed" | "inbox_binding_unavailable" | "inbox_workspace_changed" | "inbox_review_required" | "inbox_triage_required" | "inbox_result_changed" | "inbox_exception_unresolved" | "inbox_feature_disabled" | "inbox_history_limit" | null; "receipt_id": string | null; "recorded_at": string | null; "receipt_sha256": string | null };
export type Resolve = { "item_id": string; "command_kind": "review" | "triage" | "result" | "verify"; "idempotency_key": string; "request_sha256": string };
export type Result = { "item_id": string; "expected_version": number; "source_id"?: string; "source_sha256"?: string; "idempotency_key": string; "triage_receipt_id": string; "triage_receipt_sha256": string; "disposition": "local_review_complete" | "needs_human"; "evidence": string; "no_external_action_claimed": true };
export type Review = { "item_id": string; "expected_version": number; "source_id"?: string; "source_sha256"?: string; "idempotency_key": string; "workspace_id": string; "expected_workspace_revision": number; "patient_link_id": string; "reviewed_patient": true; "reviewed_exact_thread": true; "reviewed_untrusted_source": true };
export type ReviewOptions = { "contract_version": 1; "scope": Scope; "item_id": string; "item_version": number; "source_id": string; "source_sha256": string; "patient_link_id": string; "choices": Array<ReviewTarget>; "options_sha256": string };
export type ReviewTarget = { "workspace_id": string; "expected_workspace_revision": number; "appointment_id": string; "label": string; "start_at": string };
export type Scope = { "box_id": string; "owner_id": string };
export type Source = { "source_id": string; "sequence": number; "source_sha256": string; "created_at": string; "modified_at": string; "observed_at": string; "incomplete_content": boolean; "vendor": "spruce"; "conversation_id": string; "item_reference": string; "contact_id": string; "patient_link_id": string; "correspondence_version_id": string; "correspondence_public_sha256": string; "text": string; "attachments": boolean; "attachment_types": Array<"audio" | "carePlan" | "document" | "entityProfile" | "genericUrl" | "image" | "paymentRequest" | "video" | "visit" | "unknown">; "pages": boolean; "buttons": boolean; "event": boolean; "conversation_archived": boolean; "conversation_read_only": boolean; "item_response_sha256": string; "conversation_response_sha256": string; "trust": "untrusted_external_text"; "projection_sha256": string };
export type SourceMetadata = { "source_id": string; "sequence": number; "source_sha256": string; "created_at": string; "modified_at": string; "observed_at": string; "incomplete_content": boolean };
export type Summary = { "item_id": string; "version": number; "label": string; "patient_link_id": string; "source_id": string | null; "source_sha256": string | null; "state": "needs_review" | "reviewed" | "triaged" | "result_recorded" | "closed_local_review" | "needs_human"; "source_conflict": boolean; "read_issue": "authority_required" | "reference_unavailable" | "response_invalid" | "response_too_large" | "provider_throttled" | "provider_unavailable" | "request_timeout" | "source_scope_changed" | null; "binding_current": boolean; "incomplete_content": boolean; "workspace_id": string | null; "workspace_current": boolean; "classification": "administrative_review" | "clinical_human_review" | "urgent_human_review" | "source_exception" | null; "human_review_required": true; "vendor_latest_state_verified": false; "external_action_performed": false; "handoff_available": false };
export type Triage = { "item_id": string; "expected_version": number; "source_id"?: string; "source_sha256"?: string; "idempotency_key": string; "classification": "administrative_review" | "clinical_human_review" | "urgent_human_review" | "source_exception"; "due_date": string; "instructions": string; "human_disposition_required": true };
export type Verify = { "item_id": string; "expected_version": number; "source_id"?: string; "source_sha256"?: string; "idempotency_key": string; "result_receipt_id": string; "result_receipt_sha256": string; "reviewed_patient": true; "reviewed_exact_source": true; "reviewed_human_result": true; "confirm_local_review_only": true };
export type InboxContractTypes = { Availability: Availability; Bound: Bound; Catalog: Catalog; Detail: Detail; Effect: Effect; History: History; HistoryItem: HistoryItem; ReadHistory: ReadHistory; Receipt: Receipt; Resolve: Resolve; Result: Result; Review: Review; ReviewOptions: ReviewOptions; ReviewTarget: ReviewTarget; Scope: Scope; Source: Source; SourceMetadata: SourceMetadata; Summary: Summary; Triage: Triage; Verify: Verify };
export type InboxContractName = keyof InboxContractTypes;
