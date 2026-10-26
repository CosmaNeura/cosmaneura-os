"""Closed provider dispatch; no implicit provider choice or transport fallback."""

from cosmas_os.adapters.athena_allergy_read_runtime import SyntheticAthenaAllergyReads
from cosmas_os.adapters.athena_medication_read_runtime import SyntheticAthenaMedicationReads
from cosmas_os.adapters.elation_read_runtime import SyntheticElationReads
from cosmas_os.adapters.elation_sandbox_runtime import ManagedElationSandboxReads
from cosmas_os.adapters.tebra_fhir_read_runtime import SyntheticTebraFhirReads
from cosmas_os.adapters.tebra_read_runtime import SyntheticTebraReads


def runtime_provider(port):
    if type(port) in (SyntheticAthenaAllergyReads, SyntheticAthenaMedicationReads):
        return "athena"
    if type(port) in (SyntheticElationReads, ManagedElationSandboxReads):
        return "elation"
    if type(port) in (SyntheticTebraReads, SyntheticTebraFhirReads):
        return "tebra"
    return None


def runtime_protocol(port):
    return "core" if type(port) in (SyntheticAthenaAllergyReads, SyntheticAthenaMedicationReads) else "fhir" if type(port) is SyntheticTebraFhirReads else None


def runtime_clinical_scope(port):
    return "medications" if type(port) is SyntheticAthenaMedicationReads else None


class EhrReadRuntimes:
    def __init__(self, *, elation=None, tebra=None, tebra_fhir=None, athena_core=None, athena_medications=None):
        if ((elation is not None and runtime_provider(elation) != "elation")
                or (tebra is not None and type(tebra) is not SyntheticTebraReads)
                or (tebra_fhir is not None and type(tebra_fhir) is not SyntheticTebraFhirReads)
                or (athena_core is not None and type(athena_core) is not SyntheticAthenaAllergyReads)
                or (athena_medications is not None and type(athena_medications) is not SyntheticAthenaMedicationReads)):
            raise ValueError("explicit_ehr_runtimes_required")
        self._elation, self._tebra = elation, tebra
        self._tebra_fhir = tebra_fhir
        self._athena_core = athena_core
        self._athena_medications = athena_medications

    def selected(self, provider, protocol=None, clinical_scope=None):
        if clinical_scope is not None:
            return self._athena_medications if (provider, protocol, clinical_scope) == ("athena", "core", "medications") else None
        if protocol == "core":
            return self._athena_core if provider == "athena" else None
        if protocol == "fhir":
            return self._tebra_fhir if provider == "tebra" else None
        if protocol is not None:
            return None
        return self._elation if provider == "elation" else self._tebra if provider == "tebra" else None


def select_runtime(port, provider, protocol=None, clinical_scope=None):
    selected = port.selected(provider, protocol, clinical_scope) if type(port) is EhrReadRuntimes else port
    return selected if (runtime_provider(selected), runtime_protocol(selected), runtime_clinical_scope(selected)) == (provider, protocol, clinical_scope) else None
