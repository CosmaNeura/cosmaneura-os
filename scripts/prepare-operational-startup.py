"""Prepare private beta service inputs from explicit public bindings and secret references."""

from __future__ import annotations

import argparse
import copy
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from native_identity_build import load as load_native_identity
from operational_connections import add_connections
from operational_research import add_research

BASE_OS_FEATURES = {
    name: True
    for name in (
        "WORKSPACE_AI_ACTIVITY_ENABLED",
        "WORKSPACE_TEAM_SETUP_ENABLED",
        "WORKSPACE_ROUTINES_ENABLED",
        "WORKSPACE_RESEARCH_ENABLED",
        "WORKSPACE_CORE_RECORD_ENABLED",
        "WORKSPACE_CORE_CONNECTION_ENABLED",
        "WORKSPACE_CORE_APPOINTMENT_SETUP_ENABLED",
        "WORKSPACE_PREP_ENABLED",
        "WORKSPACE_PREP_WORK_ENABLED",
        "WORKSPACE_APPOINTMENTS_ENABLED",
        "WORKSPACE_CAPTURE_NOTES_ENABLED",
        "WORKSPACE_CAPTURE_CORRECTIONS_ENABLED",
        "WORKSPACE_CAPTURE_RECOVERY_ENABLED",
        "WORKSPACE_CAPTURE_SOURCE_ENABLED",
        "WORKSPACE_CAPTURE_LONG_VISITS_ENABLED",
        "WORKSPACE_SCHEDULING_ENABLED",
        "WORKSPACE_SCHEDULING_LOGIN_ENABLED",
        "WORKSPACE_SCHEDULING_ENROLLMENT_ENABLED",
        "VENDOR_SETUP_ENABLED",
        "VENDOR_WORK_ENABLED",
        "FINANCE_SETUP_ENABLED",
        "FINANCE_WORK_ENABLED",
        "PORTAL_SETUP_ENABLED",
        "PORTAL_WORK_ENABLED",
        "MEMBERSHIP_WORK_ENABLED",
        "INBOX_WORK_ENABLED",
        "INBOX_HANDOFF_ENABLED",
    )
}
BASE_OS_FEATURES.update(
    {
        name: False
        for name in (
            "WORKSPACE_RESEARCH_IO_ENABLED",
            "WORKSPACE_ATHENA_CONNECTION_ENABLED",
            "WORKSPACE_ATHENA_VISIT_LINK_ENABLED",
            "VENDOR_IO_ENABLED",
            "VENDOR_EVENTS_ENABLED",
            "FINANCE_IO_ENABLED",
            "FINANCE_EVENTS_ENABLED",
            "WORKSPACE_GOOGLE_CONNECTION_ENABLED",
            "WORKSPACE_MICROSOFT_CONNECTION_ENABLED",
        )
    }
)
CORE_FEATURES = {
    name: True
    for name in (
        "SCRIBE_CAPTURE_ENABLED",
        "SCRIBE_CAPTURE_NOTES_ENABLED",
        "SCRIBE_CAPTURE_WORKING_TRANSCRIPTS_ENABLED",
        "SCRIBE_CAPTURE_RECOVERY_ENABLED",
        "SCRIBE_CAPTURE_SOURCE_ENABLED",
        "SCRIBE_ENCOUNTER_PREP_ENABLED",
        "SCRIBE_CAPTURE_LONG_VISITS_ENABLED",
        "COMPANION_RECORD_READ_ENABLED",
        "COMPANION_ENCOUNTER_READ_ENABLED",
        "COMPANION_APPOINTMENT_SETUP_ENABLED",
        "COMPANION_APPOINTMENT_BINDINGS_ENABLED",
    )
}
CORE_FEATURES.update(
    ATHENA_APPOINTMENT_READ_ENABLED=False, ATHENA_VISIT_LINK_ENABLED=False
)
SECRET_NAMES = {
    "SCHEDULING_GOOGLE_CLIENT_SECRET",
    "SCHEDULING_LOGIN_ENCRYPTION_KEY",
    "WORKSPACE_LLM_API_KEY",
}


def exact(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError("Public binding fields are incomplete or unsupported")


def uuid(value):
    if not isinstance(value, str) or str(UUID(value)) != value or UUID(value).int == 0:
        raise ValueError("A nonzero canonical UUID is required")
    return value


def origin(value, *, allow_api_path=False):
    if not isinstance(value, str) or len(value) > 253:
        raise ValueError("An exact HTTPS origin is required")
    parsed = urlsplit(value)
    suffix = "/api" if allow_api_path and parsed.path == "/api" else ""
    if (
        parsed.scheme != "https"
        or parsed.port
        or parsed.username
        or parsed.password
        or parsed.path != suffix
        or parsed.query
        or parsed.fragment
        or not parsed.hostname
        or value != "https://" + parsed.hostname + suffix
        or not re.fullmatch(
            r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+",
            parsed.hostname,
        )
        or parsed.hostname.endswith(".localhost")
        or not parsed.hostname.rsplit(".", 1)[-1][0].isalpha()
    ):
        raise ValueError("An exact HTTPS origin is required")
    return value


def public_json(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
        raise ValueError("Use one bounded public binding file")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate public binding field")
            result[key] = value
        return result

    return json.loads(path.read_text(), object_pairs_hook=unique)


def compile_inputs(identity, bindings):
    exact(
        bindings,
        {
            "version",
            "web_origin",
            "entra_tenant_id",
            "os_runtime_client_id",
            "core",
            "scribe",
            "scheduling",
            "translation_provider",
            "secret_references",
            "capture_upload_origins",
        },
    )
    if type(bindings["version"]) is not int or bindings["version"] != 2:
        raise ValueError(
            "Service binding version 2 requires separate Sovereign and Scribe receiver identities"
        )
    origin(bindings["web_origin"])
    entra, os_client = (
        uuid(bindings["entra_tenant_id"]),
        uuid(bindings["os_runtime_client_id"]),
    )
    core, scribe, scheduling = (
        bindings[key] for key in ("core", "scribe", "scheduling")
    )
    exact(
        core,
        {
            "origin",
            "web_origin",
            "api_audience",
            "authority_tenant_ref",
            "scribe_workflow_client_id",
            "sovereign_client_id",
            "scribe_receiver_client_id",
        },
    )
    exact(scribe, {"origin", "api_audience", "practice_id"})
    exact(
        scheduling,
        {
            "origin",
            "practice_id",
            "staff_api_audience",
            "google_staff_client_id",
            "google_calendar_client_id",
        },
    )
    for item in (core, scribe):
        origin(item["origin"])
    origin(scheduling["origin"], allow_api_path=True)
    origin(core["web_origin"])
    for value in (
        core["api_audience"],
        core["scribe_workflow_client_id"],
        core["sovereign_client_id"],
        scribe["api_audience"],
        scribe["practice_id"],
        scheduling["practice_id"],
        scheduling["staff_api_audience"],
    ):
        uuid(value)
    callers = [
        os_client,
        core["sovereign_client_id"],
        core["scribe_workflow_client_id"],
    ]
    if core["scribe_receiver_client_id"] != "":
        callers.append(uuid(core["scribe_receiver_client_id"]))
    if core["api_audience"] == scribe["api_audience"] or len(set(callers)) != len(
        callers
    ):
        raise ValueError("Service audiences and caller identities must remain distinct")
    if not re.fullmatch(
        r"authority_tenant_[0-7][0-9a-hjkmnp-tv-z]{25}", core["authority_tenant_ref"]
    ):
        raise ValueError("An explicit reviewed Core tenant reference is required")
    for key in ("google_staff_client_id", "google_calendar_client_id"):
        if not re.fullmatch(
            r"[A-Za-z0-9_-]{1,200}\.apps\.googleusercontent\.com", scheduling[key]
        ):
            raise ValueError("Explicit Google client identifiers are required")
    uploads = bindings["capture_upload_origins"]
    if (
        not isinstance(uploads, list)
        or not 1 <= len(uploads) <= 4
        or len(set(uploads)) != len(uploads)
    ):
        raise ValueError("One to four distinct capture upload origins are required")
    for item in uploads:
        origin(item)
    secrets = bindings["secret_references"]
    exact(secrets, SECRET_NAMES)
    for reference in secrets.values():
        exact(reference, {"secret_name", "version"})
        if not re.fullmatch(
            r"[A-Za-z0-9-]{1,127}", reference["secret_name"]
        ) or not re.fullmatch(r"[0-9a-f]{32}", reference["version"]):
            raise ValueError("Credentials require named immutable secret references")
    provider = bindings["translation_provider"]
    exact(provider, {"resource_id", "endpoint", "deployment"})
    resource = re.fullmatch(
        r"/subscriptions/([0-9a-f-]{36})/resourceGroups/[A-Za-z0-9._()-]+/providers/Microsoft.CognitiveServices/accounts/([a-z0-9-]{1,63})",
        provider["resource_id"],
    )
    if (
        not resource
        or provider["endpoint"]
        not in {
            f"https://{resource[2]}.openai.azure.com/openai/v1",
            f"https://{resource[2]}.services.ai.azure.com/openai/v1",
        }
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", provider["deployment"])
    ):
        raise ValueError(
            "Translation must bind one existing account to its exact endpoint and deployment"
        )
    uuid(resource[1])
    features = copy.deepcopy(BASE_OS_FEATURES)
    capture = {
        "configured_service": True,
        "tenant_ids": [scribe["practice_id"]],
        "configured_job": False,
        "long_visits": True,
        "continuation": True,
        "transcript_corrections": True,
        "recovery": True,
        "source": True,
        "assembly_max_bytes": 268435456,
    }
    core_scope, scribe_scope = (
        "api://" + item["api_audience"] + "/.default" for item in (core, scribe)
    )
    result = {
        "os.services.tfvars.json": {
            "workspace_hosted_enabled": True,
            "workspace_expected_runtime_client_id": os_client,
            "workspace_features": features,
            "workspace_secret_references": secrets,
            "workspace_public_configuration": {
                "CORE_CAPTURE_ORIGIN": core["origin"],
                "CORE_CAPTURE_SCOPE": core_scope,
                "CORE_WEB_ORIGIN": core["web_origin"],
                "CORE_CONNECTION_TENANT_REF": core["authority_tenant_ref"],
                "WORKSPACE_CAPTURE_BACKEND": "core",
                "WORKSPACE_LLM_BACKEND": "azure_gpt41",
                "SCHEDULING_ORIGIN": scheduling["origin"],
                "SCHEDULING_GOOGLE_CLIENT_ID": scheduling["google_staff_client_id"],
                "SCHEDULING_ENROLLMENT_PRACTICE_ID": scheduling["practice_id"],
            },
        },
        "core.services.tfvars.json": {
            "core_beta_features": CORE_FEATURES,
            "core_beta_authority": {
                "enabled": True,
                "agent_api_enabled": True,
                "audience": core["api_audience"],
                "caller_client_id": core["sovereign_client_id"],
                "scribe_receiver_client_id": core["scribe_receiver_client_id"],
                "companion_client_id": os_client,
            },
            "core_beta_capture_upload_origins": uploads,
            "enable_scribe_workflow": True,
            "scribe_service_base_url": scribe["origin"],
            "scribe_service_scope": scribe_scope,
            "core_beta_connection_binding": {
                "clerk_issuer": identity["frontendOrigin"],
                "entra_tenant_id": entra,
                "scribe_workflow_client_id": core["scribe_workflow_client_id"],
            },
        },
        "scribe.service.tfvars.json": {
            "enable_capture_protocol": True,
            "enable_workflow_authentication": True,
            "use_postgres_repository": True,
            "workflow_api_audience": scribe["api_audience"],
            "trusted_platform_client_id": core["scribe_workflow_client_id"],
            "tenant_id": entra,
            "scribe_capture_features": capture,
        },
        "scribe.speech-grants.tfvars.json": {
            "deploy_transcription_job": True,
            "enable_transcription_job": True,
            "deploy_database_migration_job": True,
            "enable_configured_transcription_database_permissions": True,
        },
        "scribe.speech-consumer.tfvars.json": {
            "scribe_capture_features": {**capture, "configured_job": True},
            "deploy_transcription_consumer": True,
            "enable_transcription_consumer": True,
            "transcription_consumer_tenant_id": scribe["practice_id"],
        },
        "scribe.translation-grants.tfvars.json": {
            "deploy_translation_consumer": True,
            "translation_provider": provider,
            "deploy_database_migration_job": True,
            "enable_configured_translation_database_permissions": True,
        },
        "scribe.translation-consumer.tfvars.json": {
            "enable_translation_consumer": True,
            "translation_consumer_tenant_id": scribe["practice_id"],
        },
        "scheduling.services.tfvars.json": {
            "staff_api_audience": scheduling["staff_api_audience"],
            "google_staff_oidc_audience": scheduling["google_staff_client_id"],
            "google_oauth_client_id": scheduling["google_calendar_client_id"],
            "enable_google_calendar": True,
            "enable_google_staff_login": True,
            "enable_companion_connection": True,
            "enable_workspace_availability": True,
            "enable_workspace_appointment_operations": True,
        },
        "os.athena-readonly.tfvars.json": {
            "workspace_features": {
                **features,
                "WORKSPACE_ATHENA_CONNECTION_ENABLED": True,
                "WORKSPACE_ATHENA_VISIT_LINK_ENABLED": True,
            }
        },
        "core.athena-readonly.tfvars.json": {
            "core_beta_features": {
                **CORE_FEATURES,
                "ATHENA_APPOINTMENT_READ_ENABLED": True,
                "ATHENA_VISIT_LINK_ENABLED": True,
            }
        },
        "native-connection-arguments.json": {
            "cosmaneura_web_origin": core["web_origin"],
            "capture_upload_origins": uploads,
            "scheduling_google_client_id": scheduling["google_staff_client_id"],
            "scheduling_google_callback_uri": identity["apiOrigin"]
            + "/connections/scheduling/google/callback",
        },
        "service-bindings.json": {
            "version": 2,
            "status": "local_startup_inputs_prepared",
            "deployable_now": False,
            "api_origin": identity["apiOrigin"],
            "web_origin": bindings["web_origin"],
            "core_scope": core_scope,
            "scribe_scope": scribe_scope,
            "os_runtime_client_id": os_client,
            "core_sovereign_client_id": core["sovereign_client_id"],
            "core_scribe_receiver_client_id": core["scribe_receiver_client_id"],
            "core_workflow_client_id": core["scribe_workflow_client_id"],
            "practice_correspondence": {
                "core": core["authority_tenant_ref"],
                "scribe": scribe["practice_id"],
                "scheduling": scheduling["practice_id"],
            },
            "correspondence_reviewed_or_installed": False,
            "actual_service_role_grants_or_provider_acceptance": False,
            "athena_access": "read_only",
            "athena_profile_generated": False,
            "automatic_execution": False,
        },
    }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--identity", type=Path, required=True)
    parser.add_argument("--bindings", type=Path, required=True)
    parser.add_argument("--connections", type=Path)
    parser.add_argument("--research", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    identity = load_native_identity(args.identity, "desktop")["identity"]
    bindings = public_json(args.bindings)
    inputs = compile_inputs(identity, bindings)
    if args.connections is not None:
        inputs = add_connections(
            inputs, bindings, identity, public_json(args.connections)
        )
    if args.research is not None:
        inputs = add_research(inputs, public_json(args.research))
    args.output.mkdir(mode=0o700)
    marker = args.output / ".incomplete"
    marker.write_text("Service startup input preparation incomplete\n")
    for name, value in inputs.items():
        with (args.output / name).open("x") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
    client_command = [
        "node",
        str(Path(__file__).with_name("prepare-workspace-identity.mjs")),
        "--identity",
        str(args.identity),
        "--web-origin",
        bindings["web_origin"],
        "--core-web-origin",
        bindings["core"]["web_origin"],
        "--output",
        str(args.output / "clients"),
    ]
    for upload in bindings["capture_upload_origins"]:
        client_command.extend(["--capture-upload-origin", upload])
    subprocess.run(
        client_command, capture_output=True, text=True, check=True, timeout=30
    )
    marker.unlink()
    print(
        json.dumps(
            {
                "files": len(inputs),
                "status": "local_startup_inputs_prepared",
                "deployable_now": False,
            }
        )
    )


if __name__ == "__main__":
    main()
