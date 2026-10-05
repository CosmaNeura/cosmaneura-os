"""Authenticated private PDF custody using the established AES-GCM pattern.

Keys remain protected deployment inputs, never database columns. No plaintext
fallback is permitted. Key rotation/restore requires the matching retained key.
"""

import base64
import hashlib
import json
import re
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from cosmas_os.application.workspace import WorkspaceError
from cosmas_os.config import settings


def cipher():
    try:
        value = settings.fax_inbound_document_encryption_key
        encoded = value.get_secret_value() if value is not None else ""
        key = base64.b64decode(encoded, validate=True)
        if len(key) != 32 or base64.b64encode(key).decode() != encoded:
            raise ValueError
        if re.fullmatch(r"[A-Za-z0-9:_-]{1,80}", settings.fax_inbound_document_key_id) is None:
            raise ValueError
        return AESGCM(key)
    except Exception:
        raise WorkspaceError("fax_inbound_document_custody_unavailable", 409) from None


def metadata(attempt, image, grant, document_sha256, pages, byte_length, key_id):
    return dict(contract="cosmas-fax-inbound-document.v1", box_id=attempt.box_id,
        owner_id=attempt.owner_id, operation_id=attempt.operation_id, image_id=image.id,
        grant_id=grant.id, installation_sha256=grant.installation_sha256,
        source_sha256=image.source_sha256, document_sha256=document_sha256,
        pages=pages, byte_length=byte_length, key_id=key_id)


def aad(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode()


def protect(document, attempt, image, grant, pages):
    sha = hashlib.sha256(document).hexdigest()
    key_id = settings.fax_inbound_document_key_id
    associated = metadata(attempt, image, grant, sha, pages, len(document), key_id)
    nonce = secrets.token_bytes(12)
    sealed = nonce + cipher().encrypt(nonce, document, aad(associated))
    return dict(document=sealed, document_sha256=sha, pages=pages,
        document_byte_length=len(document), document_ciphertext_sha256=hashlib.sha256(sealed).hexdigest(),
        document_key_id=key_id)


def open_document(outcome, attempt, image, grant):
    try:
        sealed = outcome.document
        if (outcome.state != "acquired" or type(sealed) is not bytes
            or not 29 <= len(sealed) <= 1048576 + 28
            or outcome.document_key_id != settings.fax_inbound_document_key_id
            or hashlib.sha256(sealed).hexdigest() != outcome.document_ciphertext_sha256):
            raise ValueError
        associated = metadata(attempt, image, grant, outcome.document_sha256,
            outcome.pages, outcome.document_byte_length, outcome.document_key_id)
        document = cipher().decrypt(sealed[:12], sealed[12:], aad(associated))
        if (not document.startswith(b"%PDF-") or len(document) != outcome.document_byte_length
            or not 1 <= len(document) <= 1048576
            or hashlib.sha256(document).hexdigest() != outcome.document_sha256):
            raise ValueError
        return document
    except WorkspaceError:
        raise
    except Exception:
        raise WorkspaceError("fax_inbound_document_custody_invalid", 409) from None
