"""Read the published catalog only while opening a new selected notebook.

The narrower existing connection response budget is retained. A catalog too
large to inspect is unavailable, never evidence that no recording exists.
"""

import json
from uuid import uuid4

from cosmas_os.adapters.core_encounters import CoreDiscoveryDenied
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.core_scribe_encounters import ScribeCatalog

PATH = "/embed/v1/scribe/encounters"


def canonical_workspace(connection, discovery, bearer):
    if len(discovery.encounters) != 1:
        raise ConnectorUnavailable("core_scribe_encounter_unavailable")
    selected = discovery.encounters[0]
    token = bearer.get_secret_value()
    if not 1 <= len(token) <= 8192 or not token.isascii() or any(c.isspace() for c in token):
        raise CoreDiscoveryDenied("core_connection_access_denied")
    nonce = uuid4()
    payload = {
        "action": "list",
        "expected_actor_ref": discovery.connection.actor_ref,
        "expected_tenant_ref": discovery.connection.tenant_ref,
        "request_nonce": str(nonce),
    }

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_field")
            result[key] = value
        return result

    response = connection.http.request(
        "POST",
        connection.origin + PATH,
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Cache-Control": "no-store",
            "X-Cosmaneura-Scribe-Encounter-Version": "1",
        },
        content=json.dumps(payload).encode(),
    )
    try:
        if response.status_code in (401, 403):
            raise CoreDiscoveryDenied("core_connection_access_denied")
        if (
            response.status_code != 200
            or response.headers.get_list("x-cosmaneura-scribe-encounter-version") != ["1"]
            or response.headers.get("content-type", "").split(";", 1)[0] != "application/json"
            or "no-store" not in response.headers.get("cache-control", "").split(",")
            or str(response.request.url) != connection.origin + PATH
        ):
            raise ValueError("invalid_catalog")
        catalog = ScribeCatalog.model_validate(
            json.loads(response.content, object_pairs_hook=unique)
        )
        if (
            catalog.request_nonce != nonce
            or catalog.account.actor_ref != discovery.connection.actor_ref
            or catalog.account.tenant_ref != discovery.connection.tenant_ref
        ):
            raise ValueError("changed_catalog_account")
        matches = [
            row
            for row in catalog.encounters
            if row.appointment_ref == selected.appointment.appointment_ref
        ]
        if not matches:
            if len(catalog.encounters) == 1000:
                # The receiver caps this unpaginated catalog; absence in a full
                # response does not establish that an older recording is absent.
                raise ValueError("incomplete_scribe_catalog")
            return None
        row = matches[0]
        stamp = selected.appointment.appointment_date
        expected = (
            row.appointment_at
            if selected.appointment.timezone_known
            else row.appointment_at.replace(tzinfo=None)
        )
        if (
            row.patient_ref != selected.patient.patient_ref
            or row.patient_name != selected.patient.display_name
            or stamp != expected
        ):
            raise ValueError("changed_scribe_encounter")
        connection.budget.check()
        return row.workspace_id
    except CoreDiscoveryDenied:
        raise
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ConnectorUnavailable("core_scribe_encounter_unavailable") from None
    finally:
        response.close()
