"""Bounded team commands without reflecting private settings in error payloads."""
import json

from cosmas_os.api.team_schemas import TeamSave
from cosmas_os.application.team_setup import MAX_REQUEST_BYTES
from cosmas_os.application.workspace import WorkspaceError


def contract_header(request, *, required=False):
    values = request.headers.getlist('x-cosmas-team-contract')
    if len(values) > 1 or values and values not in (['1'], ['2'], ['3'], ['4'], ['5']):
        raise WorkspaceError('team_contract_unsupported', 426)
    if required and not values:
        raise WorkspaceError('team_contract_required', 426)
    return int(values[0]) if values else 0


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError()
        value[key] = item
    return value


async def read_team_request(request, schema):
    try:
        if (request.query_params or len(request.headers.getlist('content-type')) != 1
            or request.headers['content-type'].split(';', 1)[0].strip().lower() != 'application/json'
            or len(request.headers.getlist('authorization')) > 1
            or request.headers.getlist('content-encoding')):
            raise ValueError()
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_REQUEST_BYTES:
                raise ValueError()
            body.extend(chunk)
        value = json.loads(body, object_pairs_hook=_unique)
        if schema is TeamSave and isinstance(value, dict) and 'setup_review' in value and value['setup_review'] is None:
            raise ValueError()
        return schema.model_validate(value)
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise WorkspaceError('invalid_team_setup_request', 422) from None
