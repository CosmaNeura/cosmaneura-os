"""Callable research tools for the pre-reviewed, invented cardiac-trial fixture.

The query and source are fixed by the synthetic provider at startup. No agent
can send encounter contents to a public endpoint. Actual lookup/save services
retain the source selection; only the HTTP transport is an offline twin.
"""

import json
from typing import Any

import httpx
from pydantic import Field
from sqlalchemy.orm import Session

from cosmas_os.adapters.public_research import PublicResearch
from cosmas_os.api.research_schemas import Save, Search
from cosmas_os.application import research
from cosmas_os.application.capture_deadline import CaptureBudget
from cosmas_os.config import Settings
from lab.engine import Arguments
from lab.research_capability import QUERY, registry_response
from lab.store import LabError


class Lookup(Arguments):
    idempotency_key: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._-]+$")
    expected_workspace_revision: int = Field(ge=1)


class Resolve(Arguments):
    idempotency_key: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._-]+$")


class Selection(Lookup):
    run_id: str = Field(min_length=36, max_length=36)
    source_hashes: list[str] = Field(min_length=1, max_length=5)


RESEARCH_SCHEMAS = {
    "research_lookup_trials": (Lookup, "Look up the synthetic provider's pre-reviewed cardiac-trial query through the actual Research service and offline registry. No private query text is accepted; results do not determine eligibility."),
    "research_resolve_lookup": (Resolve, "Recover a lookup by its original key without another source request."),
    "research_save_selection": (Selection, "Save only explicitly selected, previously retrieved source hashes into real workspace evidence. Requires the exact run ID and current revision; does not recommend or approve treatment."),
}
RESEARCH_TOOL_ROLES = {name: frozenset({"research"}) for name in RESEARCH_SCHEMAS}


class ResearchTools:
    def __init__(self, app):
        self.app = app
        self.calls = 0
        configuration: dict[str, Any] = {"_env_file": None, "research_sources": "clinical_trials"}
        self.configuration = Settings(**configuration)

    def _respond(self, request):
        if (request.method != "GET" or request.url.host != "clinicaltrials.gov"
                or request.url.path != "/api/v2/studies" or dict(request.url.params) != {
                    "query.term": QUERY, "pageSize": "5", "format": "json", "countTotal": "true"}):
            raise LabError("unexpected_research_request")
        self.calls += 1
        return httpx.Response(200, json=registry_response())

    def call(self, role, name, values):
        if role not in RESEARCH_TOOL_ROLES.get(name, ()):
            raise LabError("tool_not_available_for_role")
        self.app.check_agent(role)
        args = RESEARCH_SCHEMAS[name][0].model_validate(values)
        scope = (self.app.box, self.app.owner, self.app.workspace)
        budget = CaptureBudget(30)
        with Session(self.app.engine) as session:
            if name == "research_resolve_lookup":
                result = research.resolve(session, *scope, key=args.idempotency_key)
            elif name == "research_lookup_trials":
                command = Search.model_validate_json(json.dumps({"contract_version": 1,
                    "idempotency_key": args.idempotency_key, "expected_revision": args.expected_workspace_revision,
                    "team_revision": self.app.team_revision, "bot": self.app.addresses[role],
                    "topic": "trials", "sources": ["clinical_trials"], "query": QUERY,
                    "public_query_confirmed": True}))
                with PublicResearch(self.configuration, transport=httpx.MockTransport(self._respond), budget=budget) as port:
                    result = research.search(session, *scope, request=command,
                        configured=PublicResearch.configured(self.configuration), port=port,
                        check=budget.check, reauthenticate=lambda: self.app.check_agent(role))
            else:
                command = Save.model_validate({"contract_version": 1, "idempotency_key": args.idempotency_key,
                    "expected_revision": args.expected_workspace_revision, "source_hashes": args.source_hashes})
                result = research.save(session, *scope, args.run_id, request=command,
                    check=budget.check, reauthenticate=lambda: self.app.check_agent(role))
        self.app.check_agent(role)
        return {"synthetic_only": True, "provider_transport": "offline_http_twin", "external_effects": 0,
                "authority": "synthetic_preparation_broker", "clinical_approval": False,
                "provider_reads": self.calls, "result": result,
                "next_action": "Review selected evidence; trial staff must assess eligibility. No treatment recommendation is made."}
