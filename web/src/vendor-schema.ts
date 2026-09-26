// Generated from the existing public Python contract. Do not hand-edit shapes.
// Relational checks and exact commitments are in vendor-contract.ts.
// Source SHA-256: 91aba898d9bb1c257b4c5c2632527c648e8d8e61bf21903b1e82154983bf297b
// Retirement source SHA-256: 3e3aeb1b9071fc0360db852c4562ac6710ed5560c9f551de37062c2c83763df7
export const VENDOR_SCHEMAS = {
  "Closed": {
    "additionalProperties": false,
    "properties": {},
    "title": "Closed",
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
  "VendorProposal": {
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
      "action": {
        "enum": [
          "spruce_secure_message",
          "spruce_fax",
          "spruce_media_upload",
          "srfax_fax",
          "documo_fax"
        ],
        "title": "Action",
        "type": "string"
      },
      "connection": {
        "$ref": "#/$defs/Selection"
      },
      "source": {
        "$ref": "#/$defs/ReviewedSource"
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
      "share_to_practice": {
        "title": "Share To Practice",
        "type": "boolean"
      },
      "correspondence": {
        "anyOf": [
          {
            "$ref": "#/$defs/Selection"
          },
          {
            "type": "null"
          }
        ],
        "default": null
      },
      "document": {
        "anyOf": [
          {
            "$ref": "#/$defs/Document"
          },
          {
            "type": "null"
          }
        ],
        "default": null
      },
      "message": {
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
        "default": null,
        "title": "Message"
      },
      "uploaded_media_operation_id": {
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
        "title": "Uploaded Media Operation Id"
      },
      "supersedes_operation_id": {
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
        "title": "Supersedes Operation Id"
      },
      "acknowledge_prior_uncertainty": {
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
        "title": "Acknowledge Prior Uncertainty"
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
      "action",
      "connection",
      "source",
      "due_date",
      "expected_outcome",
      "share_to_practice"
    ],
    "title": "VendorProposal",
    "type": "object",
    "x-no-null": true
  },
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
  "VendorDecision": {
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
    "title": "VendorDecision",
    "type": "object",
    "x-no-null": true
  },
  "VendorPublication": {
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
      "share_to_practice": {
        "const": true,
        "title": "Share To Practice",
        "type": "boolean",
        "x-rules": [
          "_true"
        ]
      }
    },
    "required": [
      "expected_version",
      "operation_id",
      "revision_id",
      "payload_hash",
      "idempotency_key",
      "review_sha256",
      "share_to_practice"
    ],
    "title": "VendorPublication",
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
  "VendorResult": {
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
          "reported_success",
          "reported_exception",
          "verified_in_vendor",
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
    "title": "VendorResult",
    "type": "object",
    "x-no-null": true
  },
  "VendorStaffResult": {
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
          "reported_success",
          "reported_exception"
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
    "title": "VendorStaffResult",
    "type": "object",
    "x-no-null": true
  },
  "VendorVerify": {
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
    "title": "VendorVerify",
    "type": "object",
    "x-no-null": true
  },
  "VendorResolve": {
    "additionalProperties": false,
    "properties": {
      "command_kind": {
        "enum": [
          "propose",
          "decide",
          "withdraw",
          "publish",
          "submit",
          "reconcile",
          "result",
          "verify",
          "handoff",
          "artifact_intent",
          "artifact_content"
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
    "title": "VendorResolve",
    "type": "object",
    "x-no-null": true
  },
  "VendorStaffResolve": {
    "additionalProperties": false,
    "properties": {
      "command_kind": {
        "enum": [
          "handoff",
          "result"
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
    "title": "VendorStaffResolve",
    "type": "object",
    "x-no-null": true
  },
  "VendorHandoff": {
    "additionalProperties": false,
    "properties": {
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
      }
    },
    "required": [
      "expected_version",
      "revision_id",
      "payload_hash",
      "idempotency_key",
      "kind"
    ],
    "title": "VendorHandoff",
    "type": "object",
    "x-no-null": true
  },
  "VendorArtifactIntent": {
    "additionalProperties": false,
    "properties": {
      "artifact_id": {
        "title": "Artifact Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
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
      "idempotency_key",
      "source",
      "sha256",
      "byte_length",
      "media_type"
    ],
    "title": "VendorArtifactIntent",
    "type": "object",
    "x-no-null": true
  },
  "VendorArtifactResolve": {
    "additionalProperties": false,
    "properties": {
      "command_kind": {
        "enum": [
          "artifact_intent",
          "artifact_content"
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
      "artifact_id": {
        "title": "Artifact Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      }
    },
    "required": [
      "command_kind",
      "idempotency_key",
      "request_sha256",
      "artifact_id"
    ],
    "title": "VendorArtifactResolve",
    "type": "object",
    "x-no-null": true
  },
  "VendorArtifactContent": {
    "additionalProperties": false,
    "properties": {
      "artifact_id": {
        "title": "Artifact Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "intent_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Intent Sha256",
        "type": "string"
      },
      "idempotency_key": {
        "maxLength": 100,
        "minLength": 8,
        "pattern": "^[A-Za-z0-9:_-]+$",
        "title": "Idempotency Key",
        "type": "string"
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
      "intent_sha256",
      "idempotency_key",
      "sha256",
      "byte_length",
      "media_type"
    ],
    "title": "VendorArtifactContent",
    "type": "object",
    "x-no-null": true
  },
  "Output": {
    "additionalProperties": false,
    "description": "Closed response validator; explicit nullable fields remain on the wire.",
    "properties": {},
    "title": "Output",
    "type": "object",
    "x-no-null": false
  },
  "ConnectionView": {
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
      "vendor": {
        "enum": [
          "spruce",
          "srfax",
          "documo"
        ],
        "title": "Vendor",
        "type": "string"
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
      "actions": {
        "items": {
          "enum": [
            "spruce_secure_message",
            "spruce_fax",
            "spruce_media_upload",
            "srfax_fax",
            "documo_fax"
          ],
          "type": "string"
        },
        "maxItems": 3,
        "minItems": 1,
        "title": "Actions",
        "type": "array"
      },
      "availability": {
        "enum": [
          "enabled",
          "disabled",
          "read_only",
          "revoked"
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
      "vendor",
      "environment",
      "label",
      "actions",
      "availability",
      "public_sha256"
    ],
    "title": "ConnectionView",
    "type": "object",
    "x-no-null": true
  },
  "CorrespondenceView": {
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
      "channel": {
        "enum": [
          "secure",
          "fax"
        ],
        "title": "Channel",
        "type": "string"
      },
      "recipient_label": {
        "maxLength": 80,
        "title": "Recipient Label",
        "type": "string",
        "x-rules": [
          "_text"
        ]
      },
      "destination_display": {
        "maxLength": 255,
        "title": "Destination Display",
        "type": "string",
        "x-rules": [
          "_text"
        ]
      },
      "permission": {
        "enum": [
          "reviewed",
          "expired",
          "revoked"
        ],
        "title": "Permission",
        "type": "string"
      },
      "expires_at": {
        "title": "Expires At",
        "type": "string",
        "x-rules": [
          "_timestamp"
        ]
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
      "channel",
      "recipient_label",
      "destination_display",
      "permission",
      "expires_at",
      "public_sha256"
    ],
    "title": "CorrespondenceView",
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
      "action": {
        "enum": [
          "spruce_secure_message",
          "spruce_fax",
          "spruce_media_upload",
          "srfax_fax",
          "documo_fax"
        ],
        "title": "Action",
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
      "published": {
        "title": "Published",
        "type": "boolean"
      },
      "submit_claimed": {
        "title": "Submit Claimed",
        "type": "boolean"
      },
      "dispatch": {
        "enum": [
          "not_started",
          "invocation_started",
          "proved_not_dispatched",
          "unconfirmed",
          "response_observed"
        ],
        "title": "Dispatch",
        "type": "string"
      },
      "acceptance": {
        "enum": [
          "not_observed",
          "accepted",
          "rejected",
          "unconfirmed"
        ],
        "title": "Acceptance",
        "type": "string"
      },
      "transport": {
        "enum": [
          "not_observed",
          "pending",
          "delivered",
          "failed",
          "unknown"
        ],
        "title": "Transport",
        "type": "string"
      },
      "conflicting_evidence": {
        "title": "Conflicting Evidence",
        "type": "boolean"
      },
      "result": {
        "enum": [
          "none",
          "recorded_success",
          "recorded_exception"
        ],
        "title": "Result",
        "type": "string"
      },
      "verification": {
        "enum": [
          "pending",
          "verified",
          "exception_unresolved"
        ],
        "title": "Verification",
        "type": "string"
      },
      "due_date": {
        "title": "Due Date",
        "type": "string",
        "x-rules": [
          "_day"
        ]
      },
      "outcome_excerpt": {
        "maxLength": 160,
        "title": "Outcome Excerpt",
        "type": "string",
        "x-rules": [
          "_text"
        ]
      },
      "responsible_id": {
        "title": "Responsible Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
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
      "action",
      "state",
      "published",
      "submit_claimed",
      "dispatch",
      "acceptance",
      "transport",
      "conflicting_evidence",
      "result",
      "verification",
      "due_date",
      "outcome_excerpt",
      "responsible_id",
      "observation_head",
      "evidence_sha256"
    ],
    "title": "Summary",
    "type": "object",
    "x-no-null": true
  },
  "Availability": {
    "additionalProperties": false,
    "properties": {
      "allowed": {
        "title": "Allowed",
        "type": "boolean"
      },
      "reason": {
        "enum": [
          "available",
          "feature_disabled",
          "owner_only",
          "not_current",
          "not_approved",
          "expired",
          "source_changed",
          "selection_changed",
          "permission_unavailable",
          "artifact_unavailable",
          "submit_already_claimed",
          "reference_unavailable",
          "original_account_unavailable",
          "read_in_progress",
          "history_limit",
          "result_required",
          "manual_verification_required",
          "exception_unresolved",
          "already_published",
          "closed"
        ],
        "title": "Reason",
        "type": "string"
      }
    },
    "required": [
      "allowed",
      "reason"
    ],
    "title": "Availability",
    "type": "object",
    "x-no-null": true
  },
  "ActionAvailability": {
    "additionalProperties": false,
    "properties": {
      "approve": {
        "$ref": "#/$defs/Availability"
      },
      "reject": {
        "$ref": "#/$defs/Availability"
      },
      "withdraw": {
        "$ref": "#/$defs/Availability"
      },
      "publish": {
        "$ref": "#/$defs/Availability"
      },
      "submit": {
        "$ref": "#/$defs/Availability"
      },
      "reconcile": {
        "$ref": "#/$defs/Availability"
      },
      "result": {
        "$ref": "#/$defs/Availability"
      },
      "verify": {
        "$ref": "#/$defs/Availability"
      }
    },
    "required": [
      "approve",
      "reject",
      "withdraw",
      "publish",
      "submit",
      "reconcile",
      "result",
      "verify"
    ],
    "title": "ActionAvailability",
    "type": "object",
    "x-no-null": true
  },
  "UploadedMedia": {
    "additionalProperties": false,
    "properties": {
      "operation_id": {
        "title": "Operation Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "document": {
        "$ref": "#/$defs/Document"
      }
    },
    "required": [
      "operation_id",
      "document"
    ],
    "title": "UploadedMedia",
    "type": "object",
    "x-no-null": true
  },
  "SupersedesView": {
    "additionalProperties": false,
    "properties": {
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
      "action": {
        "enum": [
          "spruce_secure_message",
          "spruce_fax",
          "spruce_media_upload",
          "srfax_fax",
          "documo_fax"
        ],
        "title": "Action",
        "type": "string"
      },
      "prior_dispatch": {
        "enum": [
          "not_started",
          "invocation_started",
          "proved_not_dispatched",
          "unconfirmed",
          "response_observed"
        ],
        "title": "Prior Dispatch",
        "type": "string"
      },
      "prior_acceptance": {
        "enum": [
          "not_observed",
          "accepted",
          "rejected",
          "unconfirmed"
        ],
        "title": "Prior Acceptance",
        "type": "string"
      },
      "prior_transport": {
        "enum": [
          "not_observed",
          "pending",
          "delivered",
          "failed",
          "unknown"
        ],
        "title": "Prior Transport",
        "type": "string"
      },
      "uncertainty_acknowledged": {
        "const": true,
        "title": "Uncertainty Acknowledged",
        "type": "boolean",
        "x-rules": [
          "_true"
        ]
      }
    },
    "required": [
      "ticket_id",
      "operation_id",
      "action",
      "prior_dispatch",
      "prior_acceptance",
      "prior_transport",
      "uncertainty_acknowledged"
    ],
    "title": "SupersedesView",
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
      "operation_id": {
        "title": "Operation Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "action": {
        "enum": [
          "spruce_secure_message",
          "spruce_fax",
          "spruce_media_upload",
          "srfax_fax",
          "documo_fax"
        ],
        "title": "Action",
        "type": "string"
      },
      "connection": {
        "$ref": "#/$defs/ConnectionView"
      },
      "source": {
        "$ref": "#/$defs/ReviewedSource"
      },
      "correspondence": {
        "anyOf": [
          {
            "$ref": "#/$defs/CorrespondenceView"
          },
          {
            "type": "null"
          }
        ],
        "default": null
      },
      "document": {
        "anyOf": [
          {
            "$ref": "#/$defs/Document"
          },
          {
            "type": "null"
          }
        ],
        "default": null
      },
      "uploaded_media": {
        "anyOf": [
          {
            "$ref": "#/$defs/UploadedMedia"
          },
          {
            "type": "null"
          }
        ],
        "default": null
      },
      "message": {
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
        "default": null,
        "title": "Message"
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
      "share_to_practice": {
        "title": "Share To Practice",
        "type": "boolean"
      },
      "expires_at": {
        "title": "Expires At",
        "type": "string",
        "x-rules": [
          "_timestamp"
        ]
      },
      "supersedes": {
        "anyOf": [
          {
            "$ref": "#/$defs/SupersedesView"
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
      "revision_id",
      "operation_id",
      "action",
      "connection",
      "source",
      "due_date",
      "expected_outcome",
      "share_to_practice",
      "expires_at"
    ],
    "title": "Review",
    "type": "object",
    "x-no-null": true
  },
  "Person": {
    "additionalProperties": false,
    "properties": {
      "id": {
        "title": "Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "name": {
        "maxLength": 80,
        "title": "Name",
        "type": "string",
        "x-rules": [
          "_text"
        ]
      },
      "available": {
        "title": "Available",
        "type": "boolean"
      }
    },
    "required": [
      "id",
      "name",
      "available"
    ],
    "title": "Person",
    "type": "object",
    "x-no-null": true
  },
  "HumanResult": {
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
      "actor": {
        "$ref": "#/$defs/Person"
      },
      "disposition": {
        "enum": [
          "reported_success",
          "reported_exception",
          "verified_in_vendor",
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
      "recorded_at": {
        "title": "Recorded At",
        "type": "string",
        "x-rules": [
          "_timestamp"
        ]
      },
      "observation_head": {
        "$ref": "#/$defs/ObservationHead"
      }
    },
    "required": [
      "receipt_id",
      "receipt_sha256",
      "actor",
      "disposition",
      "evidence",
      "recorded_at",
      "observation_head"
    ],
    "title": "HumanResult",
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
      "workspace_id": {
        "title": "Workspace Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "view_version": {
        "maximum": 2147483647,
        "minimum": 1,
        "title": "View Version",
        "type": "integer"
      },
      "observed_at": {
        "title": "Observed At",
        "type": "string",
        "x-rules": [
          "_timestamp"
        ]
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
            "$ref": "#/$defs/HumanResult"
          },
          {
            "type": "null"
          }
        ]
      },
      "availability": {
        "$ref": "#/$defs/ActionAvailability"
      }
    },
    "required": [
      "contract_version",
      "workspace_id",
      "view_version",
      "observed_at",
      "summary",
      "review",
      "review_sha256",
      "latest_result",
      "availability"
    ],
    "title": "Detail",
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
      "workspace_id": {
        "title": "Workspace Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "entry_revision": {
        "maximum": 2147483647,
        "minimum": 1,
        "title": "Entry Revision",
        "type": "integer"
      },
      "enabled": {
        "title": "Enabled",
        "type": "boolean"
      },
      "connections": {
        "items": {
          "$ref": "#/$defs/ConnectionView"
        },
        "maxItems": 10,
        "title": "Connections",
        "type": "array"
      },
      "correspondences": {
        "items": {
          "$ref": "#/$defs/CorrespondenceView"
        },
        "maxItems": 10,
        "title": "Correspondences",
        "type": "array"
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
      "workspace_id",
      "entry_revision",
      "enabled",
      "connections",
      "correspondences",
      "source",
      "observed_at"
    ],
    "title": "Options",
    "type": "object",
    "x-no-null": false
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
      "workspace_id": {
        "title": "Workspace Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "items": {
        "items": {
          "$ref": "#/$defs/Summary"
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
            "pattern": "^[\\x21-\\x7e]+$",
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Next Cursor"
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
      "workspace_id",
      "items",
      "next_cursor",
      "observed_at"
    ],
    "title": "Catalog",
    "type": "object",
    "x-no-null": false
  },
  "Observation": {
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
      "kind": {
        "enum": [
          "submission",
          "transport",
          "dispatch"
        ],
        "title": "Kind",
        "type": "string"
      },
      "observed_at": {
        "title": "Observed At",
        "type": "string",
        "x-rules": [
          "_timestamp"
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
      "acceptance": {
        "anyOf": [
          {
            "enum": [
              "accepted",
              "rejected",
              "unconfirmed"
            ],
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "default": null,
        "title": "Acceptance"
      },
      "transport": {
        "anyOf": [
          {
            "enum": [
              "pending",
              "delivered",
              "failed",
              "unknown"
            ],
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "default": null,
        "title": "Transport"
      },
      "dispatch": {
        "anyOf": [
          {
            "enum": [
              "not_started",
              "invocation_started",
              "proved_not_dispatched",
              "unconfirmed",
              "response_observed"
            ],
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "default": null,
        "title": "Dispatch"
      },
      "pages_total": {
        "anyOf": [
          {
            "maximum": 1000000,
            "minimum": 0,
            "type": "integer"
          },
          {
            "type": "null"
          }
        ],
        "default": null,
        "title": "Pages Total"
      },
      "pages_delivered": {
        "anyOf": [
          {
            "maximum": 1000000,
            "minimum": 0,
            "type": "integer"
          },
          {
            "type": "null"
          }
        ],
        "default": null,
        "title": "Pages Delivered"
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
      "kind",
      "observed_at",
      "recorded_at",
      "sha256"
    ],
    "title": "Observation",
    "type": "object",
    "x-no-null": true
  },
  "ObservationPage": {
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
          "$ref": "#/$defs/Observation"
        },
        "maxItems": 20,
        "title": "Observations",
        "type": "array"
      },
      "head": {
        "$ref": "#/$defs/ObservationHead"
      },
      "next_cursor": {
        "anyOf": [
          {
            "maxLength": 512,
            "minLength": 1,
            "pattern": "^[\\x21-\\x7e]+$",
            "type": "string"
          },
          {
            "type": "null"
          }
        ],
        "title": "Next Cursor"
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
      "ticket_id",
      "operation_id",
      "observations",
      "head",
      "next_cursor",
      "observed_at"
    ],
    "title": "ObservationPage",
    "type": "object",
    "x-no-null": false
  },
  "Scope": {
    "additionalProperties": false,
    "properties": {
      "kind": {
        "enum": [
          "workspace",
          "practice_work"
        ],
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
    "title": "Scope",
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
      "receipt_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Receipt Sha256",
        "type": "string"
      }
    },
    "required": [
      "ticket_id",
      "operation_id",
      "revision_id",
      "payload_hash",
      "receipt_id",
      "effect_version",
      "recorded_at",
      "receipt_sha256"
    ],
    "title": "Effect",
    "type": "object",
    "x-no-null": true
  },
  "EffectSummary": {
    "additionalProperties": false,
    "properties": {
      "effect": {
        "enum": [
          "proposed",
          "revised",
          "approved",
          "rejected",
          "withdrawn",
          "published",
          "submit_claimed",
          "read_claimed",
          "result_recorded",
          "verified",
          "handoff_recorded"
        ],
        "title": "Effect",
        "type": "string"
      },
      "publication_recorded": {
        "title": "Publication Recorded",
        "type": "boolean"
      }
    },
    "required": [
      "effect",
      "publication_recorded"
    ],
    "title": "EffectSummary",
    "type": "object",
    "x-no-null": true
  },
  "CommandResponse": {
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
          "withdraw",
          "publish",
          "submit",
          "reconcile",
          "result",
          "verify",
          "handoff",
          "artifact_intent",
          "artifact_content"
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
          "unconfirmed",
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
      "summary": {
        "anyOf": [
          {
            "$ref": "#/$defs/EffectSummary"
          },
          {
            "type": "null"
          }
        ]
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
      "summary",
      "observed_at"
    ],
    "title": "CommandResponse",
    "type": "object",
    "x-no-null": false
  },
  "ArtifactMetadata": {
    "additionalProperties": false,
    "properties": {
      "artifact_id": {
        "title": "Artifact Id",
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
      "source": {
        "$ref": "#/$defs/ReviewedSource"
      },
      "document": {
        "$ref": "#/$defs/Document"
      },
      "intent_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Intent Sha256",
        "type": "string"
      },
      "state": {
        "enum": [
          "empty",
          "receiving",
          "ready",
          "quarantined"
        ],
        "title": "State",
        "type": "string"
      },
      "generation": {
        "maximum": 2147483647,
        "minimum": 0,
        "title": "Generation",
        "type": "integer"
      },
      "lease_until": {
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
        "title": "Lease Until"
      }
    },
    "required": [
      "artifact_id",
      "version",
      "source",
      "document",
      "intent_sha256",
      "state",
      "generation",
      "lease_until"
    ],
    "title": "ArtifactMetadata",
    "type": "object",
    "x-no-null": false
  },
  "ArtifactEffect": {
    "additionalProperties": false,
    "properties": {
      "artifact_id": {
        "title": "Artifact Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
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
      "receipt_sha256": {
        "pattern": "^[a-f0-9]{64}$",
        "title": "Receipt Sha256",
        "type": "string"
      }
    },
    "required": [
      "artifact_id",
      "receipt_id",
      "effect_version",
      "recorded_at",
      "receipt_sha256"
    ],
    "title": "ArtifactEffect",
    "type": "object",
    "x-no-null": true
  },
  "ArtifactResponse": {
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
          "artifact_intent",
          "artifact_content"
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
          "unconfirmed",
          "not_found"
        ],
        "title": "Outcome",
        "type": "string"
      },
      "effect": {
        "anyOf": [
          {
            "$ref": "#/$defs/ArtifactEffect"
          },
          {
            "type": "null"
          }
        ]
      },
      "artifact": {
        "anyOf": [
          {
            "$ref": "#/$defs/ArtifactMetadata"
          },
          {
            "type": "null"
          }
        ]
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
      "artifact",
      "observed_at"
    ],
    "title": "ArtifactResponse",
    "type": "object",
    "x-no-null": false
  },
  "SharedVendorStatus": {
    "additionalProperties": false,
    "properties": {
      "action": {
        "enum": [
          "spruce_secure_message",
          "spruce_fax",
          "spruce_media_upload",
          "srfax_fax",
          "documo_fax"
        ],
        "title": "Action",
        "type": "string"
      },
      "operation_id": {
        "title": "Operation Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "submit_claimed": {
        "title": "Submit Claimed",
        "type": "boolean"
      },
      "acceptance": {
        "enum": [
          "not_observed",
          "accepted",
          "rejected",
          "unconfirmed"
        ],
        "title": "Acceptance",
        "type": "string"
      },
      "transport": {
        "enum": [
          "not_observed",
          "pending",
          "delivered",
          "failed",
          "unknown"
        ],
        "title": "Transport",
        "type": "string"
      },
      "conflicting_evidence": {
        "title": "Conflicting Evidence",
        "type": "boolean"
      },
      "result": {
        "enum": [
          "none",
          "recorded_success",
          "recorded_exception"
        ],
        "title": "Result",
        "type": "string"
      },
      "verification": {
        "enum": [
          "pending",
          "verified",
          "exception_unresolved"
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
      "action",
      "operation_id",
      "submit_claimed",
      "acceptance",
      "transport",
      "conflicting_evidence",
      "result",
      "verification",
      "observation_head",
      "evidence_sha256"
    ],
    "title": "SharedVendorStatus",
    "type": "object",
    "x-no-null": true
  },
  "SharedVendorWork": {
    "additionalProperties": false,
    "properties": {
      "work_kind": {
        "const": "vendor_delivery",
        "title": "Work Kind",
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
      "ready_for_review": {
        "title": "Ready For Review",
        "type": "boolean"
      },
      "historical": {
        "title": "Historical",
        "type": "boolean"
      },
      "publication_receipt_id": {
        "title": "Publication Receipt Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "body": {
        "maxLength": 500,
        "title": "Body",
        "type": "string",
        "x-rules": [
          "_text"
        ]
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
      "viewer_id": {
        "title": "Viewer Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "originator": {
        "$ref": "#/$defs/Person"
      },
      "responsible": {
        "$ref": "#/$defs/Person"
      },
      "vendor_work": {
        "$ref": "#/$defs/SharedVendorStatus"
      }
    },
    "required": [
      "work_kind",
      "ticket_id",
      "version",
      "revision_id",
      "payload_hash",
      "state",
      "ready_for_review",
      "historical",
      "publication_receipt_id",
      "body",
      "due_date",
      "expected_outcome",
      "viewer_id",
      "originator",
      "responsible",
      "vendor_work"
    ],
    "title": "SharedVendorWork",
    "type": "object",
    "x-no-null": true
  },
  "SharedOffer": {
    "additionalProperties": false,
    "properties": {
      "id": {
        "title": "Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "from": {
        "$ref": "#/$defs/Person"
      },
      "to": {
        "$ref": "#/$defs/Person"
      }
    },
    "required": [
      "id",
      "from",
      "to"
    ],
    "title": "SharedOffer",
    "type": "object",
    "x-no-null": true
  },
  "SharedHandoff": {
    "additionalProperties": false,
    "properties": {
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
      "actor": {
        "$ref": "#/$defs/Person"
      },
      "from": {
        "$ref": "#/$defs/Person"
      },
      "to": {
        "$ref": "#/$defs/Person"
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
      "created_at": {
        "title": "Created At",
        "type": "string",
        "x-rules": [
          "_timestamp"
        ]
      }
    },
    "required": [
      "id",
      "kind",
      "actor",
      "from",
      "to",
      "offer_id",
      "created_at"
    ],
    "title": "SharedHandoff",
    "type": "object",
    "x-no-null": false
  },
  "SharedVendorDetail": {
    "additionalProperties": false,
    "properties": {
      "work_kind": {
        "const": "vendor_delivery",
        "title": "Work Kind",
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
      "ready_for_review": {
        "title": "Ready For Review",
        "type": "boolean"
      },
      "historical": {
        "title": "Historical",
        "type": "boolean"
      },
      "publication_receipt_id": {
        "title": "Publication Receipt Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "body": {
        "maxLength": 500,
        "title": "Body",
        "type": "string",
        "x-rules": [
          "_text"
        ]
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
      "viewer_id": {
        "title": "Viewer Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "originator": {
        "$ref": "#/$defs/Person"
      },
      "responsible": {
        "$ref": "#/$defs/Person"
      },
      "vendor_work": {
        "$ref": "#/$defs/SharedVendorStatus"
      },
      "pending_offer": {
        "anyOf": [
          {
            "$ref": "#/$defs/SharedOffer"
          },
          {
            "type": "null"
          }
        ]
      },
      "handoffs": {
        "items": {
          "$ref": "#/$defs/SharedHandoff"
        },
        "maxItems": 201,
        "title": "Handoffs",
        "type": "array"
      },
      "latest_result": {
        "anyOf": [
          {
            "$ref": "#/$defs/HumanResult"
          },
          {
            "type": "null"
          }
        ]
      }
    },
    "required": [
      "work_kind",
      "ticket_id",
      "version",
      "revision_id",
      "payload_hash",
      "state",
      "ready_for_review",
      "historical",
      "publication_receipt_id",
      "body",
      "due_date",
      "expected_outcome",
      "viewer_id",
      "originator",
      "responsible",
      "vendor_work",
      "pending_offer",
      "handoffs",
      "latest_result"
    ],
    "title": "SharedVendorDetail",
    "type": "object",
    "x-no-null": false
  },
  "VendorRetire": {
    "additionalProperties": false,
    "properties": {
      "command_kind": {
        "enum": [
          "decide",
          "submit",
          "verify"
        ],
        "title": "Command Kind",
        "type": "string"
      },
      "request": {
        "anyOf": [
          {
            "$ref": "#/$defs/VendorVerify"
          },
          {
            "$ref": "#/$defs/VendorDecision"
          },
          {
            "$ref": "#/$defs/BoundCommand"
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
    "title": "VendorRetire",
    "type": "object",
    "x-no-null": true
  },
  "RetirementScope": {
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
    "title": "RetirementScope",
    "type": "object",
    "x-no-null": true
  },
  "RetirementRecord": {
    "additionalProperties": false,
    "properties": {
      "receipt_id": {
        "title": "Receipt Id",
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
      "retired_at": {
        "title": "Retired At",
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
      "receipt_id",
      "ticket_id",
      "revision_id",
      "operation_id",
      "payload_hash",
      "retired_at",
      "receipt_sha256"
    ],
    "title": "RetirementRecord",
    "type": "object",
    "x-no-null": true
  },
  "RetirementResponse": {
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
        "$ref": "#/$defs/RetirementScope"
      },
      "command_kind": {
        "enum": [
          "decide",
          "submit",
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
        "const": "retired",
        "title": "Outcome",
        "type": "string"
      },
      "effect": {
        "title": "Effect",
        "type": "null"
      },
      "summary": {
        "title": "Summary",
        "type": "null"
      },
      "retirement": {
        "$ref": "#/$defs/RetirementRecord"
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
      "summary",
      "retirement",
      "observed_at"
    ],
    "title": "RetirementResponse",
    "type": "object",
    "x-no-null": false
  },
  "VendorPreparationRetire": {
    "additionalProperties": false,
    "properties": {
      "command_kind": {
        "enum": [
          "propose",
          "artifact_intent",
          "artifact_content"
        ],
        "title": "Command Kind",
        "type": "string"
      },
      "request": {
        "anyOf": [
          {
            "$ref": "#/$defs/VendorProposal"
          },
          {
            "$ref": "#/$defs/VendorArtifactIntent"
          },
          {
            "$ref": "#/$defs/VendorArtifactContent"
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
    "title": "VendorPreparationRetire",
    "type": "object",
    "x-no-null": true
  },
  "PreparationRetirementRecord": {
    "additionalProperties": false,
    "properties": {
      "receipt_id": {
        "title": "Receipt Id",
        "type": "string",
        "x-rules": [
          "_uuid"
        ]
      },
      "retired_at": {
        "title": "Retired At",
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
      "receipt_id",
      "retired_at",
      "receipt_sha256"
    ],
    "title": "PreparationRetirementRecord",
    "type": "object",
    "x-no-null": true
  },
  "PreparationCommandRetirementResponse": {
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
        "$ref": "#/$defs/RetirementScope"
      },
      "command_kind": {
        "const": "propose",
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
      "summary": {
        "title": "Summary",
        "type": "null"
      },
      "retirement": {
        "$ref": "#/$defs/PreparationRetirementRecord"
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
      "summary",
      "retirement",
      "observed_at"
    ],
    "title": "PreparationCommandRetirementResponse",
    "type": "object",
    "x-no-null": false
  },
  "PreparationArtifactRetirementResponse": {
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
        "$ref": "#/$defs/RetirementScope"
      },
      "command_kind": {
        "enum": [
          "artifact_intent",
          "artifact_content"
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
      "artifact": {
        "title": "Artifact",
        "type": "null"
      },
      "retirement": {
        "$ref": "#/$defs/PreparationRetirementRecord"
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
      "artifact",
      "retirement",
      "observed_at"
    ],
    "title": "PreparationArtifactRetirementResponse",
    "type": "object",
    "x-no-null": false
  }
} as const;

export type Closed = {  };
export type Selection = { "id": string; "revision": number; "public_sha256": string };
export type ReviewedSource = { "kind": "reviewed_note"; "note_id": string; "content_sha256": string; "source_fingerprint": string };
export type Document = { "artifact_id": string; "sha256": string; "byte_length": number; "media_type": "application/pdf" };
export type Revision = { "ticket_id": string; "expected_version": number; "revision_id": string; "payload_hash": string };
export type VendorProposal = { "expected_workspace_revision": number; "idempotency_key": string; "proposed_operation_id": string; "action": "spruce_secure_message" | "spruce_fax" | "spruce_media_upload" | "srfax_fax" | "documo_fax"; "connection": Selection; "source": ReviewedSource; "due_date": string; "expected_outcome": string; "share_to_practice": boolean; "correspondence"?: Selection; "document"?: Document; "message"?: string; "uploaded_media_operation_id"?: string; "supersedes_operation_id"?: string; "acknowledge_prior_uncertainty"?: true; "revises"?: Revision };
export type BoundCommand = { "expected_version": number; "operation_id": string; "revision_id": string; "payload_hash": string; "idempotency_key": string };
export type VendorDecision = { "expected_version": number; "operation_id": string; "revision_id": string; "payload_hash": string; "idempotency_key": string; "review_sha256": string; "choice": "approve" | "reject" };
export type VendorPublication = { "expected_version": number; "operation_id": string; "revision_id": string; "payload_hash": string; "idempotency_key": string; "review_sha256": string; "share_to_practice": true };
export type ObservationHead = { "sequence": number; "sha256": string };
export type VendorResult = { "expected_version": number; "operation_id": string; "revision_id": string; "payload_hash": string; "idempotency_key": string; "observation_head": ObservationHead; "evidence_sha256": string; "disposition": "reported_success" | "reported_exception" | "verified_in_vendor" | "unable_to_establish"; "evidence": string };
export type VendorStaffResult = { "expected_version": number; "operation_id": string; "revision_id": string; "payload_hash": string; "idempotency_key": string; "observation_head": ObservationHead; "evidence_sha256": string; "disposition": "reported_success" | "reported_exception"; "evidence": string };
export type VendorVerify = { "expected_version": number; "operation_id": string; "revision_id": string; "payload_hash": string; "idempotency_key": string; "result_receipt_id": string; "result_receipt_sha256": string; "observation_head": ObservationHead; "evidence_sha256": string; "reviewed_result": true; "reviewed_observations": true; "outcome_confirmed": true; "reviewed_conflicting_evidence": boolean };
export type VendorResolve = { "command_kind": "propose" | "decide" | "withdraw" | "publish" | "submit" | "reconcile" | "result" | "verify" | "handoff" | "artifact_intent" | "artifact_content"; "idempotency_key": string; "request_sha256": string };
export type VendorStaffResolve = { "command_kind": "handoff" | "result"; "idempotency_key": string; "request_sha256": string };
export type VendorHandoff = { "expected_version": number; "revision_id": string; "payload_hash": string; "idempotency_key": string; "kind": "offer" | "accept" | "decline" | "recall" | "reclaim"; "recipient_id"?: string; "offer_id"?: string };
export type VendorArtifactIntent = { "artifact_id": string; "idempotency_key": string; "source": ReviewedSource; "sha256": string; "byte_length": number; "media_type": "application/pdf" };
export type VendorArtifactResolve = { "command_kind": "artifact_intent" | "artifact_content"; "idempotency_key": string; "request_sha256": string; "artifact_id": string };
export type VendorArtifactContent = { "artifact_id": string; "intent_sha256": string; "idempotency_key": string; "sha256": string; "byte_length": number; "media_type": "application/pdf" };
export type Output = {  };
export type ConnectionView = { "id": string; "revision": number; "vendor": "spruce" | "srfax" | "documo"; "environment": "production" | "sandbox"; "label": string; "actions": Array<"spruce_secure_message" | "spruce_fax" | "spruce_media_upload" | "srfax_fax" | "documo_fax">; "availability": "enabled" | "disabled" | "read_only" | "revoked"; "public_sha256": string };
export type CorrespondenceView = { "id": string; "revision": number; "connection_id": string; "channel": "secure" | "fax"; "recipient_label": string; "destination_display": string; "permission": "reviewed" | "expired" | "revoked"; "expires_at": string; "public_sha256": string };
export type Summary = { "ticket_id": string; "version": number; "revision_id": string; "operation_id": string; "payload_hash": string; "action": "spruce_secure_message" | "spruce_fax" | "spruce_media_upload" | "srfax_fax" | "documo_fax"; "state": "pending_approval" | "approved" | "rejected" | "withdrawn" | "superseded" | "closed"; "published": boolean; "submit_claimed": boolean; "dispatch": "not_started" | "invocation_started" | "proved_not_dispatched" | "unconfirmed" | "response_observed"; "acceptance": "not_observed" | "accepted" | "rejected" | "unconfirmed"; "transport": "not_observed" | "pending" | "delivered" | "failed" | "unknown"; "conflicting_evidence": boolean; "result": "none" | "recorded_success" | "recorded_exception"; "verification": "pending" | "verified" | "exception_unresolved"; "due_date": string; "outcome_excerpt": string; "responsible_id": string; "observation_head": ObservationHead; "evidence_sha256": string };
export type Availability = { "allowed": boolean; "reason": "available" | "feature_disabled" | "owner_only" | "not_current" | "not_approved" | "expired" | "source_changed" | "selection_changed" | "permission_unavailable" | "artifact_unavailable" | "submit_already_claimed" | "reference_unavailable" | "original_account_unavailable" | "read_in_progress" | "history_limit" | "result_required" | "manual_verification_required" | "exception_unresolved" | "already_published" | "closed" };
export type ActionAvailability = { "approve": Availability; "reject": Availability; "withdraw": Availability; "publish": Availability; "submit": Availability; "reconcile": Availability; "result": Availability; "verify": Availability };
export type UploadedMedia = { "operation_id": string; "document": Document };
export type SupersedesView = { "ticket_id": string; "operation_id": string; "action": "spruce_secure_message" | "spruce_fax" | "spruce_media_upload" | "srfax_fax" | "documo_fax"; "prior_dispatch": "not_started" | "invocation_started" | "proved_not_dispatched" | "unconfirmed" | "response_observed"; "prior_acceptance": "not_observed" | "accepted" | "rejected" | "unconfirmed"; "prior_transport": "not_observed" | "pending" | "delivered" | "failed" | "unknown"; "uncertainty_acknowledged": true };
export type Review = { "ticket_id": string; "revision_id": string; "operation_id": string; "action": "spruce_secure_message" | "spruce_fax" | "spruce_media_upload" | "srfax_fax" | "documo_fax"; "connection": ConnectionView; "source": ReviewedSource; "correspondence"?: CorrespondenceView; "document"?: Document; "uploaded_media"?: UploadedMedia; "message"?: string; "due_date": string; "expected_outcome": string; "share_to_practice": boolean; "expires_at": string; "supersedes"?: SupersedesView };
export type Person = { "id": string; "name": string; "available": boolean };
export type HumanResult = { "receipt_id": string; "receipt_sha256": string; "actor": Person; "disposition": "reported_success" | "reported_exception" | "verified_in_vendor" | "unable_to_establish"; "evidence": string; "recorded_at": string; "observation_head": ObservationHead };
export type Detail = { "contract_version": 1; "workspace_id": string; "view_version": number; "observed_at": string; "summary": Summary; "review": Review; "review_sha256": string; "latest_result": HumanResult | null; "availability": ActionAvailability };
export type Options = { "contract_version": 1; "workspace_id": string; "entry_revision": number; "enabled": boolean; "connections": Array<ConnectionView>; "correspondences": Array<CorrespondenceView>; "source": ReviewedSource | null; "observed_at": string };
export type Catalog = { "contract_version": 1; "workspace_id": string; "items": Array<Summary>; "next_cursor": string | null; "observed_at": string };
export type Observation = { "id": string; "sequence": number; "operation_id": string; "kind": "submission" | "transport" | "dispatch"; "observed_at": string; "recorded_at": string; "sha256": string; "acceptance"?: "accepted" | "rejected" | "unconfirmed"; "transport"?: "pending" | "delivered" | "failed" | "unknown"; "dispatch"?: "not_started" | "invocation_started" | "proved_not_dispatched" | "unconfirmed" | "response_observed"; "pages_total"?: number; "pages_delivered"?: number; "safe_error"?: "connector_disabled" | "capability_unavailable" | "connection_changed" | "authority_required" | "approval_changed" | "request_invalid" | "artifact_changed" | "response_invalid" | "response_too_large" | "transport_unconfirmed" | "provider_rejected" | "provider_throttled" | "duplicate_unresolved" | "signature_invalid" | "event_untrusted" | "reference_unavailable" };
export type ObservationPage = { "contract_version": 1; "ticket_id": string; "operation_id": string; "observations": Array<Observation>; "head": ObservationHead; "next_cursor": string | null; "observed_at": string };
export type Scope = { "kind": "workspace" | "practice_work"; "id": string };
export type Effect = { "ticket_id": string; "operation_id": string; "revision_id": string; "payload_hash": string; "receipt_id": string; "effect_version": number; "recorded_at": string; "receipt_sha256": string };
export type EffectSummary = { "effect": "proposed" | "revised" | "approved" | "rejected" | "withdrawn" | "published" | "submit_claimed" | "read_claimed" | "result_recorded" | "verified" | "handoff_recorded"; "publication_recorded": boolean };
export type CommandResponse = { "contract_version": 1; "scope": Scope; "command_kind": "propose" | "decide" | "withdraw" | "publish" | "submit" | "reconcile" | "result" | "verify" | "handoff" | "artifact_intent" | "artifact_content"; "idempotency_key": string; "request_sha256": string; "outcome": "recorded" | "unconfirmed" | "not_found"; "effect": Effect | null; "summary": EffectSummary | null; "observed_at": string };
export type ArtifactMetadata = { "artifact_id": string; "version": number; "source": ReviewedSource; "document": Document; "intent_sha256": string; "state": "empty" | "receiving" | "ready" | "quarantined"; "generation": number; "lease_until": string | null };
export type ArtifactEffect = { "artifact_id": string; "receipt_id": string; "effect_version": number; "recorded_at": string; "receipt_sha256": string };
export type ArtifactResponse = { "contract_version": 1; "scope": Scope; "command_kind": "artifact_intent" | "artifact_content"; "idempotency_key": string; "request_sha256": string; "outcome": "recorded" | "unconfirmed" | "not_found"; "effect": ArtifactEffect | null; "artifact": ArtifactMetadata | null; "observed_at": string };
export type SharedVendorStatus = { "action": "spruce_secure_message" | "spruce_fax" | "spruce_media_upload" | "srfax_fax" | "documo_fax"; "operation_id": string; "submit_claimed": boolean; "acceptance": "not_observed" | "accepted" | "rejected" | "unconfirmed"; "transport": "not_observed" | "pending" | "delivered" | "failed" | "unknown"; "conflicting_evidence": boolean; "result": "none" | "recorded_success" | "recorded_exception"; "verification": "pending" | "verified" | "exception_unresolved"; "observation_head": ObservationHead; "evidence_sha256": string };
export type SharedVendorWork = { "work_kind": "vendor_delivery"; "ticket_id": string; "version": number; "revision_id": string; "payload_hash": string; "state": "pending_approval" | "approved" | "rejected" | "withdrawn" | "superseded" | "closed"; "ready_for_review": boolean; "historical": boolean; "publication_receipt_id": string; "body": string; "due_date": string; "expected_outcome": string; "viewer_id": string; "originator": Person; "responsible": Person; "vendor_work": SharedVendorStatus };
export type SharedOffer = { "id": string; "from": Person; "to": Person };
export type SharedHandoff = { "id": string; "kind": "offer" | "accept" | "decline" | "recall" | "reclaim"; "actor": Person; "from": Person; "to": Person; "offer_id": string | null; "created_at": string };
export type SharedVendorDetail = { "work_kind": "vendor_delivery"; "ticket_id": string; "version": number; "revision_id": string; "payload_hash": string; "state": "pending_approval" | "approved" | "rejected" | "withdrawn" | "superseded" | "closed"; "ready_for_review": boolean; "historical": boolean; "publication_receipt_id": string; "body": string; "due_date": string; "expected_outcome": string; "viewer_id": string; "originator": Person; "responsible": Person; "vendor_work": SharedVendorStatus; "pending_offer": SharedOffer | null; "handoffs": Array<SharedHandoff>; "latest_result": HumanResult | null };
export type VendorRetire = { "command_kind": "decide" | "submit" | "verify"; "request": VendorVerify | VendorDecision | BoundCommand; "request_sha256": string };
export type RetirementScope = { "kind": "workspace"; "id": string };
export type RetirementRecord = { "receipt_id": string; "ticket_id": string; "revision_id": string; "operation_id": string; "payload_hash": string; "retired_at": string; "receipt_sha256": string };
export type RetirementResponse = { "contract_version": 1; "scope": RetirementScope; "command_kind": "decide" | "submit" | "verify"; "idempotency_key": string; "request_sha256": string; "outcome": "retired"; "effect": null; "summary": null; "retirement": RetirementRecord; "observed_at": string };
export type VendorPreparationRetire = { "command_kind": "propose" | "artifact_intent" | "artifact_content"; "request": VendorProposal | VendorArtifactIntent | VendorArtifactContent; "request_sha256": string };
export type PreparationRetirementRecord = { "receipt_id": string; "retired_at": string; "receipt_sha256": string };
export type PreparationCommandRetirementResponse = { "contract_version": 1; "scope": RetirementScope; "command_kind": "propose"; "idempotency_key": string; "request_sha256": string; "outcome": "retired"; "effect": null; "summary": null; "retirement": PreparationRetirementRecord; "observed_at": string };
export type PreparationArtifactRetirementResponse = { "contract_version": 1; "scope": RetirementScope; "command_kind": "artifact_intent" | "artifact_content"; "idempotency_key": string; "request_sha256": string; "outcome": "retired"; "effect": null; "artifact": null; "retirement": PreparationRetirementRecord; "observed_at": string };
export type VendorContractTypes = { Closed: Closed; Selection: Selection; ReviewedSource: ReviewedSource; Document: Document; Revision: Revision; VendorProposal: VendorProposal; BoundCommand: BoundCommand; VendorDecision: VendorDecision; VendorPublication: VendorPublication; ObservationHead: ObservationHead; VendorResult: VendorResult; VendorStaffResult: VendorStaffResult; VendorVerify: VendorVerify; VendorResolve: VendorResolve; VendorStaffResolve: VendorStaffResolve; VendorHandoff: VendorHandoff; VendorArtifactIntent: VendorArtifactIntent; VendorArtifactResolve: VendorArtifactResolve; VendorArtifactContent: VendorArtifactContent; Output: Output; ConnectionView: ConnectionView; CorrespondenceView: CorrespondenceView; Summary: Summary; Availability: Availability; ActionAvailability: ActionAvailability; UploadedMedia: UploadedMedia; SupersedesView: SupersedesView; Review: Review; Person: Person; HumanResult: HumanResult; Detail: Detail; Options: Options; Catalog: Catalog; Observation: Observation; ObservationPage: ObservationPage; Scope: Scope; Effect: Effect; EffectSummary: EffectSummary; CommandResponse: CommandResponse; ArtifactMetadata: ArtifactMetadata; ArtifactEffect: ArtifactEffect; ArtifactResponse: ArtifactResponse; SharedVendorStatus: SharedVendorStatus; SharedVendorWork: SharedVendorWork; SharedOffer: SharedOffer; SharedHandoff: SharedHandoff; SharedVendorDetail: SharedVendorDetail; VendorRetire: VendorRetire; RetirementScope: RetirementScope; RetirementRecord: RetirementRecord; RetirementResponse: RetirementResponse; VendorPreparationRetire: VendorPreparationRetire; PreparationRetirementRecord: PreparationRetirementRecord; PreparationCommandRetirementResponse: PreparationCommandRetirementResponse; PreparationArtifactRetirementResponse: PreparationArtifactRetirementResponse };
export type VendorContractName = keyof VendorContractTypes;
