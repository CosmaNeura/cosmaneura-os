"""Closed provider selection shared by dark installation checks and execution."""

from cosmas_os.adapters.vendor_connectors.documo_inbound import DocumoInbound
from cosmas_os.adapters.vendor_connectors.spruce_fax_inbound import SpruceFaxInbound
from cosmas_os.adapters.vendor_connectors.srfax_inbound import SRFaxInbound


def adapter(vendor):
    return {"srfax": SRFaxInbound, "documo": DocumoInbound, "spruce": SpruceFaxInbound}[vendor]
