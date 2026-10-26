"""Closed provider dispatch; no implicit provider choice or transport fallback."""

from cosmas_os.adapters.elation_read_runtime import SyntheticElationReads
from cosmas_os.adapters.elation_sandbox_runtime import ManagedElationSandboxReads
from cosmas_os.adapters.tebra_fhir_read_runtime import SyntheticTebraFhirReads
from cosmas_os.adapters.tebra_read_runtime import SyntheticTebraReads


def runtime_provider(port):
    if type(port) in (SyntheticElationReads, ManagedElationSandboxReads):
        return "elation"
    if type(port) in (SyntheticTebraReads, SyntheticTebraFhirReads):
        return "tebra"
    return None


def runtime_protocol(port):
    return "fhir" if type(port) is SyntheticTebraFhirReads else None


class EhrReadRuntimes:
    def __init__(self, *, elation=None, tebra=None, tebra_fhir=None):
        if ((elation is not None and runtime_provider(elation) != "elation")
                or (tebra is not None and type(tebra) is not SyntheticTebraReads)
                or (tebra_fhir is not None and type(tebra_fhir) is not SyntheticTebraFhirReads)):
            raise ValueError("explicit_ehr_runtimes_required")
        self._elation, self._tebra = elation, tebra
        self._tebra_fhir = tebra_fhir

    def selected(self, provider, protocol=None):
        if protocol == "fhir":
            return self._tebra_fhir if provider == "tebra" else None
        if protocol is not None:
            return None
        return self._elation if provider == "elation" else self._tebra if provider == "tebra" else None


def select_runtime(port, provider, protocol=None):
    selected = port.selected(provider, protocol) if type(port) is EhrReadRuntimes else port
    return selected if runtime_provider(selected) == provider and runtime_protocol(selected) == protocol else None
