"""Prepare the existing public Research reader without making publisher calls."""

from __future__ import annotations

import copy
import hashlib
import json

from operational_connections import exact, secret_reference
from research_contract import SOURCES, DatasetMapping

MAPPED_SOURCES = {"cms_open_data", "medicare_care_compare"}


def add_research(inputs, research):
    exact(research, {"version", "enabled", "sources", "dataset_mappings", "openfda_api_key"})
    if type(research["version"]) is not int or research["version"] != 1:
        raise ValueError("Unsupported research configuration version")
    if type(research["enabled"]) is not bool:
        raise ValueError("Research I/O selection must be an explicit boolean")
    sources = research["sources"]
    if (
        not isinstance(sources, list)
        or not 1 <= len(sources) <= len(SOURCES)
        or any(not isinstance(source, str) or source not in SOURCES for source in sources)
        or len(set(sources)) != len(sources)
    ):
        raise ValueError("Select distinct supported public research sources")
    mappings = research["dataset_mappings"]
    exact(mappings, set(sources) & MAPPED_SOURCES)
    try:
        for source, mapping in mappings.items():
            DatasetMapping.parse(source, mapping)
        encoded = json.dumps(mappings, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError, KeyError):
        raise ValueError("Research datasets require the selected runtime's versioned mapping") from None
    if len(encoded) > 16384:
        raise ValueError("Research dataset mappings exceed the deployment field limit")
    reference = research["openfda_api_key"]
    if ("openfda" in sources) != (reference is not None):
        raise ValueError("Select openFDA together with its immutable API key reference")
    if reference is not None:
        reference = secret_reference(reference)
        occupied = inputs["os.services.tfvars.json"]["workspace_secret_references"].values()
        if reference in occupied:
            raise ValueError("openFDA requires a separate immutable secret reference")

    result = copy.deepcopy(inputs)
    config = result["os.services.tfvars.json"]
    config["workspace_features"].update(
        WORKSPACE_RESEARCH_ENABLED=True,
        WORKSPACE_RESEARCH_IO_ENABLED=research["enabled"],
    )
    config["workspace_public_configuration"].update(
        RESEARCH_SOURCES=",".join(sources), RESEARCH_DATASET_MAPPINGS=encoded,
    )
    if reference is not None:
        config["workspace_secret_references"]["RESEARCH_OPENFDA_API_KEY"] = reference
    result["os.athena-readonly.tfvars.json"]["workspace_features"].update(
        WORKSPACE_RESEARCH_ENABLED=True,
        WORKSPACE_RESEARCH_IO_ENABLED=research["enabled"],
    )
    result["service-bindings.json"]["research_sources"] = sources.copy()
    result["research-configuration.json"] = {
        "version": 1,
        "io_enabled": research["enabled"],
        "sources": [
            {"id": source, "label": SOURCES[source][0], "documentation_url": SOURCES[source][3]}
            for source in sources
        ],
        "dataset_mappings_sha256": hashlib.sha256(encoded.encode()).hexdigest(),
        "openfda_secret_reference_supplied": reference is not None,
        "public_query_confirmation_required": True,
        "private_encounter_context_inherited": False,
        "publisher_acceptance_performed": False,
    }
    return result
