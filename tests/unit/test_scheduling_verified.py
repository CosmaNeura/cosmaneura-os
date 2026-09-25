from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
from tests.unit.test_scheduling_contract import HEADERS, NOW, SLOT, client
from tests.unit.test_scheduling_contract import selection as selection
from tests.unit.test_scheduling_contract import window as window

from cosmas_os.ports.bot_capabilities import ConnectorUnavailable


def envelope(request, selected, period):
    return dict(contract_version="1", request_nonce=request.url.params['requestNonce'],
        practice_id=str(selected.practice_id), actor_id=str(selected.expected_actor_id),
        practitioner_id=str(selected.practitioner_id), location_id=str(selected.location_id),
        appointment_type_id=str(selected.appointment_type_id), range_start=period.starts_at.isoformat(),
        range_end=period.ends_at.isoformat(), google=dict(provider='google', calendar_id='primary',
            connection_id=str(uuid4()), connected_at=(NOW-timedelta(days=1)).isoformat(), checked_at=NOW.isoformat()), slots=[SLOT])


def test_verified_request_is_bound_to_nonce_staff_and_window(selection, window):
    calls = []
    def handler(request):
        assert request.url.path.endswith('/availability/verified')
        value = envelope(request, selection, window)
        calls.append(value['request_nonce'])
        return httpx.Response(200, json=value, headers=HEADERS)
    port = client(handler)
    try:
        for _ in range(2):
            result = port.verified_availability(selection, window)
            assert result.google.provider == 'google' and result.selection == selection
            assert result.slots[0].starts_at == NOW
        assert calls[0] != calls[1]
    finally:
        port.close()


@pytest.mark.parametrize('fault', ['practice_id','actor_id','practitioner_id','location_id','appointment_type_id',
    'request_nonce','range_start','range_end','stale','future','google','missing_provider','missing_calendar','legacy','version','extra','slot','connection_time'])
def test_substituted_or_unattested_receipt_is_unavailable(selection, window, fault):
    def handler(request):
        value = envelope(request, selection, window)
        if fault in {'practice_id','actor_id','practitioner_id','location_id','appointment_type_id','request_nonce'}:
            value[fault] = str(uuid4())
        elif fault in {'range_start','range_end'}:
            value[fault] = (NOW+timedelta(hours=1)).isoformat()
        elif fault in {'stale','future'}:
            value['google']['checked_at'] = (NOW+timedelta(seconds=-31 if fault=='stale' else 6)).isoformat()
        elif fault == 'google':
            del value['google']
        elif fault in {'missing_provider','missing_calendar'}:
            del value['google']['provider' if fault == 'missing_provider' else 'calendar_id']
        elif fault == 'legacy':
            value = [SLOT]
        elif fault == 'version':
            value['contract_version'] = '2'
        elif fault == 'extra':
            value['private_text'] = 'PRIVATE'
        elif fault == 'slot':
            value['slots'] = [SLOT, SLOT]
        else:
            value['google']['connected_at'] = (NOW+timedelta(days=1)).isoformat()
        return httpx.Response(200, json=value, headers=HEADERS)
    port = client(handler)
    try:
        with pytest.raises(ConnectorUnavailable) as caught:
            port.verified_availability(selection, window)
        assert 'PRIVATE' not in str(caught.value)
    finally:
        port.close()


def test_verified_requires_reviewed_staff_actor_before_credentials(selection, window):
    port = client(lambda r: pytest.fail('no I/O'), staff_credential=lambda s: pytest.fail('no credentials'))
    try:
        with pytest.raises(ConnectorUnavailable):
            port.verified_availability(selection.model_copy(update={'expected_actor_id':None}), window)
    finally:
        port.close()
