"""Gmail metadata observation using the existing personal-account read contract.

This adapter cannot obtain bodies, attachments, provider modification versions,
patient correspondence, or clinical priority. Observation time orders local
captures; it is not a Gmail history/version claim.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from cosmas_os.domain.hashing import payload_hash


class GoogleHeader(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    subject: str = Field(max_length=998)
    sender: str = Field(max_length=320)
    received_at: str
    is_read: bool


class GoogleInboxMetadata:
    """No new grant or transport: delegate only the existing bounded mail read."""

    def __init__(self, connection, identity):
        if connection.provider != "google":
            raise ValueError("google_account_required")
        self.connection, self.identity = connection, identity

    def read(self):
        value = self.connection.mail(self.identity)
        if value["kind"] != "mail" or len(value["items"]) > 10:
            raise ValueError("invalid_google_metadata")
        observed = datetime.fromisoformat(value["observed_at"])
        if observed.tzinfo is None:
            raise ValueError("invalid_google_observation_time")
        items = [GoogleHeader.model_validate(row).model_dump() for row in value["items"]]
        if len({row["id"] for row in items}) != len(items):
            raise ValueError("duplicate_google_message")
        return {**value, "items": items, "provider": "google", "metadata_only": True,
            "incomplete_message": True, "classification": "needs_human",
            "clinical_priority": None, "provider_revision": None,
            "source_sha256": payload_hash(value),
            "limits": "Up to 10 Subject/From headers and read labels only. No body, attachments, patient match or provider history version. Full-message access requires a separately reviewed future permission contract."}
