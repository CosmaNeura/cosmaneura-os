"""Closed provider dispatch; no implicit provider choice or transport fallback."""

from cosmas_os.adapters.elation_read_runtime import SyntheticElationReads
from cosmas_os.adapters.elation_sandbox_runtime import ManagedElationSandboxReads
from cosmas_os.adapters.tebra_read_runtime import SyntheticTebraReads


def runtime_provider(port):
    if type(port) in (SyntheticElationReads, ManagedElationSandboxReads):
        return "elation"
    if type(port) is SyntheticTebraReads:
        return "tebra"
    return None


class EhrReadRuntimes:
    def __init__(self, *, elation=None, tebra=None):
        if ((elation is not None and runtime_provider(elation) != "elation")
                or (tebra is not None and type(tebra) is not SyntheticTebraReads)):
            raise ValueError("explicit_ehr_runtimes_required")
        self._elation, self._tebra = elation, tebra

    def selected(self, provider):
        return self._elation if provider == "elation" else self._tebra if provider == "tebra" else None


def select_runtime(port, provider):
    selected = port.selected(provider) if type(port) is EhrReadRuntimes else port
    return selected if runtime_provider(selected) == provider else None
