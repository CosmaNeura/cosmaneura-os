"""Bind existing optional connectors to public clients and immutable secret references."""

from __future__ import annotations

import copy
import re
from uuid import UUID

GOOGLE_SCOPES = "openid email https://www.googleapis.com/auth/gmail.metadata"
GOOGLE_CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events.readonly"
GOOGLE_FULL_MESSAGE_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GOOGLE_SOURCE_FLAGS = {
    "full_message": "WORKSPACE_GOOGLE_MESSAGE_ENABLED",
    "calendar": "WORKSPACE_GOOGLE_CALENDAR_ENABLED",
}
MICROSOFT_SCOPES = "offline_access User.Read Mail.Read Calendars.Read"
MANAGED_FLAGS = {
    "vendor_io": "VENDOR_IO_ENABLED",
    "vendor_events": "VENDOR_EVENTS_ENABLED",
    "finance_io": "FINANCE_IO_ENABLED",
    "finance_events": "FINANCE_EVENTS_ENABLED",
}


def exact(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError("Connector fields are incomplete or unsupported")


def uuid(value):
    if not isinstance(value, str) or str(UUID(value)) != value or UUID(value).int == 0:
        raise ValueError("Connector identity requires a nonzero canonical UUID")
    return value


def secret_reference(value, *, manifest=False):
    exact(
        value,
        {"secret_name", "version", "sha256"}
        if manifest
        else {"secret_name", "version"},
    )
    if (
        not isinstance(value["secret_name"], str)
        or not re.fullmatch(r"[A-Za-z0-9-]{1,127}", value["secret_name"])
        or not isinstance(value["version"], str)
        or not re.fullmatch(r"[0-9a-f]{32}", value["version"])
        or manifest
        and (
            not isinstance(value["sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", value["sha256"])
            or value["sha256"] == "0" * 64
        )
    ):
        raise ValueError("Connectors require exact immutable secret references")
    return copy.deepcopy(value)


def add_connections(inputs, bindings, identity, connections):
    """Return a complete override without reading credentials or installed accounts."""
    exact(connections, {"version", "google", "microsoft", "managed_services"})
    if type(connections["version"]) is not int or connections["version"] != 1:
        raise ValueError("Unsupported connector version")
    result = copy.deepcopy(inputs)
    os_input = result["os.services.tfvars.json"]
    features = os_input["workspace_features"]
    public = os_input["workspace_public_configuration"]
    secrets = os_input["workspace_secret_references"]
    native = result["native-connection-arguments.json"]
    registration = {
        "version": 1,
        "accounts": {},
        "provider_registration_performed": False,
        "account_consent_performed": False,
        "managed_manifest_installed": False,
    }
    occupied = {(value["secret_name"], value["version"]) for value in secrets.values()}

    def oauth_secret(name, value):
        reference = secret_reference(value)
        key = (reference["secret_name"], reference["version"])
        if key in occupied:
            raise ValueError(
                "OAuth clients and custody require separate secret references"
            )
        occupied.add(key)
        secrets[name] = reference

    google = connections["google"]
    if google is not None:
        fields = {"client_id", "client_secret", "encryption_key"}
        if isinstance(google, dict) and "enabled" in google:
            fields.add("enabled")
        exact(google, fields)
        selected_sources = google.get("enabled", dict.fromkeys(GOOGLE_SOURCE_FLAGS, False))
        exact(selected_sources, GOOGLE_SOURCE_FLAGS)
        for name, flag in GOOGLE_SOURCE_FLAGS.items():
            value = selected_sources[name]
            if type(value) is not bool:
                raise ValueError("Google source selections must be explicit booleans")
            features[flag] = value
        client = google["client_id"]
        if (
            not isinstance(client, str)
            or not re.fullmatch(
                r"[A-Za-z0-9_-]{1,200}\.apps\.googleusercontent\.com", client
            )
            or client
            in {
                bindings["scheduling"]["google_staff_client_id"],
                bindings["scheduling"]["google_calendar_client_id"],
            }
        ):
            raise ValueError("Gmail requires its separate Google web client")
        callback = identity["apiOrigin"] + "/connections/google/callback"
        features["WORKSPACE_GOOGLE_CONNECTION_ENABLED"] = True
        public["GOOGLE_CONNECTION_CLIENT_ID"] = client
        oauth_secret("GOOGLE_CONNECTION_CLIENT_SECRET", google["client_secret"])
        oauth_secret("GOOGLE_CONNECTION_ENCRYPTION_KEY", google["encryption_key"])
        native.update(
            google_connection_client_id=client, google_connection_callback_uri=callback
        )
        registration["accounts"]["google"] = {
            "client_id": client,
            "callback_uri": callback,
            # Normal sign-in already requests Calendar, independently of the
            # source-save feature. Existing metadata-only grants remain accepted.
            "scopes": (GOOGLE_SCOPES + " " + GOOGLE_CALENDAR_SCOPE).split(),
            "accepted_legacy_scopes": GOOGLE_SCOPES.split(),
            "access": "inbox_metadata_and_calendar_summaries_read",
            "source_features": copy.deepcopy(selected_sources),
            "separate_from_scheduling": True,
        }
        if selected_sources["full_message"]:
            # This is a separate human start_full_mail intent, never an implicit
            # expansion of the normal sign-in request or evidence of consent.
            registration["accounts"]["google"]["full_message_consent_scopes"] = (
                GOOGLE_SCOPES + " " + GOOGLE_CALENDAR_SCOPE + " " + GOOGLE_FULL_MESSAGE_SCOPE
            ).split()

    microsoft = connections["microsoft"]
    if microsoft is not None:
        exact(microsoft, {"tenant_id", "client_id", "client_secret", "encryption_key"})
        tenant, client = uuid(microsoft["tenant_id"]), uuid(microsoft["client_id"])
        callback = identity["apiOrigin"] + "/connections/microsoft/callback"
        features["WORKSPACE_MICROSOFT_CONNECTION_ENABLED"] = True
        public.update(
            MICROSOFT_CONNECTION_TENANT_ID=tenant, MICROSOFT_CONNECTION_CLIENT_ID=client
        )
        oauth_secret("MICROSOFT_CONNECTION_CLIENT_SECRET", microsoft["client_secret"])
        oauth_secret("MICROSOFT_CONNECTION_ENCRYPTION_KEY", microsoft["encryption_key"])
        native.update(
            microsoft_connection_tenant_id=tenant,
            microsoft_connection_client_id=client,
            microsoft_connection_callback_uri=callback,
        )
        registration["accounts"]["microsoft"] = {
            "tenant_id": tenant,
            "client_id": client,
            "callback_uri": callback,
            "scopes": MICROSOFT_SCOPES.split(),
            "access": "inbox_and_calendar_read",
            "account_type": "configured_work_or_school_tenant",
        }

    managed = connections["managed_services"]
    if managed is not None:
        exact(managed, {"manifest", "secret_references", "enabled"})
        os_input["workspace_managed_manifest"] = secret_reference(
            managed["manifest"], manifest=True
        )
        references = managed["secret_references"]
        if not isinstance(references, dict) or len(references) > 90:
            raise ValueError(
                "Managed credential references must be a bounded named map"
            )
        for name, reference in references.items():
            if not re.fullmatch(r"COSMAS_MANAGED_SECRET_[A-Z][A-Z0-9_]{0,63}", name):
                raise ValueError("Unsupported managed credential environment name")
            secrets[name] = secret_reference(reference)
        exact(managed["enabled"], MANAGED_FLAGS)
        for key, flag in MANAGED_FLAGS.items():
            value = managed["enabled"][key]
            if type(value) is not bool:
                raise ValueError("Managed I/O selections must be explicit booleans")
            features[flag] = value
        registration["managed_services"] = {
            "manifest_sha256": managed["manifest"]["sha256"],
            "credential_environment_names": sorted(references),
            "selected_io": copy.deepcopy(managed["enabled"]),
            "account_review_or_action_approval_performed": False,
        }

    # Terraform replaces maps wholesale. Preserve every baseline feature in both
    # normal startup and the separate Athena read-only activation layer.
    athena = result["os.athena-readonly.tfvars.json"]["workspace_features"]
    athena.update(features)
    athena.update(
        WORKSPACE_ATHENA_CONNECTION_ENABLED=True,
        WORKSPACE_ATHENA_VISIT_LINK_ENABLED=True,
    )
    result["service-bindings.json"]["optional_connections"] = sorted(
        registration["accounts"]
    )
    result["service-bindings.json"]["managed_manifest_reference_supplied"] = (
        managed is not None
    )
    result["provider-registration.json"] = registration
    return result
