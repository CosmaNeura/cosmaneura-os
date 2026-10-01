"""An incomplete or incompatible sender must never become an installed account."""

from dataclasses import replace

import pytest
from tests.unit.test_vendor_readiness import installation

from cosmas_os.application.vendor_settings import Catalog


@pytest.mark.parametrize("vendor", ["spruce", "srfax", "documo", "efax"])
def test_documented_sender_is_admitted(vendor):
    item = installation(vendor)
    assert Catalog((item,)).installations


@pytest.mark.parametrize("routing", [
    {"caller_id": "2125550100"},
    {"caller_id": "2125550100", "sender_email": ""},
    {"caller_id": "2125550100", "sender_email": "not-an-email"},
    {"caller_id": "bad", "sender_email": "fax@example.invalid"},
])
def test_incomplete_srfax_sender_cannot_appear_available(routing):
    with pytest.raises(ValueError):
        Catalog((replace(installation("srfax"), routing=routing),))


@pytest.mark.parametrize("vendor", ["spruce", "documo", "efax"])
def test_sender_email_is_not_silently_accepted_by_other_providers(vendor):
    item = installation(vendor)
    with pytest.raises(ValueError):
        Catalog((replace(item, routing={**item.routing, "sender_email": "fax@example.invalid"}),))
