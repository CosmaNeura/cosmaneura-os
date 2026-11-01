"""Scoped Scheduling reads and private F-8 proposals on real local services.

The product services accept a human owner and a Follow-up read grant. This
explicit synthetic broker checks the calling agent, then uses that exact grant;
it creates no production agent authority. Fixture correspondence and resource
restrictions are reviewed by the scripted constructor before tools run. Only
the separate test driver can approve/execute against an injected MockTransport.
"""

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
from pydantic import Field, SecretStr, ValidationError
from sqlalchemy.orm import sessionmaker

from cosmas_os.adapters.scheduling_actions import HttpSchedulingAppointments
from cosmas_os.api.capture_schemas import CaptureBotSelection
from cosmas_os.api.scheduling_schemas import AppointmentPrepare
from cosmas_os.api.workspace_schemas import IdempotencyKey
from cosmas_os.application import (
    appointment_execution,
    appointment_work,
    provider_team,
    team_resources,
    team_setup,
    workspace,
    workspace_appointments,
    workspace_scheduling,
)
from cosmas_os.config import settings
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.models import (
    AppointmentWork,
    EncounterWorkspace,
    ExternalIdentity,
    SchedulingAccount,
    SchedulingPatientAccount,
)
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.scheduling import AvailabilitySlot, AvailabilityWindow
from lab.engine import Arguments
from lab.store import LabError

BROKER_AUTHORITY = "synthetic_scheduling_broker_only; current follow_up grant; no production agent authority"
SCENARIOS = ("normal", "unavailable", "grant_unavailable", "stale_slot", "lost_prepare_reply", "lost_submit_reply", "calendar_pending")


class SchedulingAvailabilityArgs(Arguments):
    timezone: Literal["America/New_York", "UTC"] = "America/New_York"


class SchedulingPrepareObservedArgs(Arguments):
    slot_ref: str = Field(pattern=r"^slot-(ny|utc)-[12]$")
    idempotency_key: IdempotencyKey
    expected_workspace_revision: int = Field(strict=True, ge=1)


class SchedulingInspectPreparedArgs(Arguments):
    proposal_ref: str = Field(pattern=r"^appointment-[0-9a-f]{16}$")


SCHEDULING_SCHEMAS = {
    "scheduling_read_availability": (SchedulingAvailabilityArgs, "Read current verified availability for the fixed synthetic Scheduling account and patient workspace. Choose New York or UTC display; the window is server selected. Save the returned slot_ref and workspace_revision. Times include UTC offsets, availability is not a reservation."),
    "scheduling_prepare_observed": (SchedulingPrepareObservedArgs, "Prepare an exact private F-8 appointment proposal from a slot your active role already observed. Use its slot_ref, workspace revision and stable request key. The server retains patient, staff, resource and time bindings and rechecks that exact slot. No approval or booking occurs; repeat identical arguments to recover a lost preparation response."),
    "scheduling_list_proposals": (Arguments, "Read up to 20 existing appointment proposals in this fixed workspace, with exact proposal refs, IDs, hashes and saved states. List before inspecting a proposal; has_more and next_cursor honestly indicate omitted work. No receiver calls or appointment submission occur."),
    "scheduling_inspect_prepared": (SchedulingInspectPreparedArgs, "Read the exact saved appointment proposal previously listed by your active role. Use its compact proposal_ref; IDs and hashes are retained internally. Appointment saved and Calendar updated are separate receipt outcomes. This tool cannot approve, submit, retry or refresh the receiver."),
}
SCHEDULING_TOOL_ROLES = {name: frozenset({"chief", "visit_prep", "follow_up"}) for name in SCHEDULING_SCHEMAS}


class _ObservedAppointments(HttpSchedulingAppointments):
    """Retain the actual read receipt and fence a changed Google connection."""

    last_availability = None
    expected_google = None

    def verified_availability(self, selection, window):
        result = super().verified_availability(selection, window)
        coverage = str(result.google.connection_id), result.google.connected_at.isoformat()
        if self.expected_google is not None and coverage != self.expected_google:
            raise ConnectorUnavailable("scheduling_observation_changed")
        self.last_availability = result
        return result


class SchedulingTools:
    def __init__(self, app, root, scenario="normal"):
        if scenario not in SCENARIOS:
            raise LabError("unknown_scheduling_tool_scenario")
        self.app, self.root, self.scenario = app, Path(root), scenario
        self.sessions = sessionmaker(app.engine, expire_on_commit=False)
        self.scope = app.box, app.owner, app.workspace
        self.identity_id, self.account_id, self.patient_mapping_id = map(str, (uuid4(), uuid4(), uuid4()))
        self.remote = {name: str(uuid4()) for name in ("practice_id", "actor_id", "practitioner_id", "location_id", "appointment_type_id", "patient_id", "connection_id")}
        self.window = AvailabilityWindow(starts_at=datetime(2026, 11, 1, 4, tzinfo=UTC), ends_at=datetime(2026, 11, 1, 9, tzinfo=UTC))
        # Two distinct 01:30 local times during the New York autumn DST fold.
        self.slots = tuple(AvailabilitySlot(starts_at=datetime(2026, 11, 1, hour, 30, tzinfo=UTC), ends_at=datetime(2026, 11, 1, hour, 50, tzinfo=UTC)) for hour in (5, 6))
        self.calls, self.journal, self.observations, self.preparations, self.catalog_reads = [], {}, {}, {}, {}
        self.calendar_state = "pending" if scenario == "calendar_pending" else "synced"
        self.connected_at = datetime.now(UTC) - timedelta(hours=1)
        self.lost_prepare_reply = scenario == "lost_prepare_reply"
        self.lost_submit_reply = scenario == "lost_submit_reply"
        self._seed_fixture()
        self.port = _ObservedAppointments("https://scheduling.example.invalid", lambda _: SecretStr("invented-scheduling-staff-token"), transport=httpx.MockTransport(self._respond))

    def close(self):
        self.port.close()

    def _seed_fixture(self):
        """Test-driver setup; never reachable through a model-callable tool."""
        now = datetime.now(UTC)
        with self.sessions() as s:
            workspace.read(s, *self.scope)
            current_workspace = s.get(EncounterWorkspace, self.app.workspace)
            if current_workspace is None:
                raise LabError("scheduling_fixture_workspace_missing")
            s.add(ExternalIdentity(id=self.identity_id, box_id=self.app.box, principal_id=self.app.owner,
                issuer="https://scheduling-identity.example.invalid", subject="lab_" + self.identity_id,
                organization_id="synthetic_clinic", active=True, reviewed_by="synthetic_test_driver", evidence_ref="lab:scheduling-fixture"))
            s.flush()
            account = SchedulingAccount(id=self.account_id, external_identity_id=self.identity_id,
                **{name: self.remote[name] for name in ("practice_id", "actor_id", "practitioner_id", "location_id", "appointment_type_id")},
                label="Invented Scheduling practice", reviewed_by="synthetic_test_driver", evidence_ref="lab:scheduling-fixture", reviewed_at=now)
            s.add(account)
            s.add(SchedulingPatientAccount(id=self.patient_mapping_id, box_id=self.app.box,
                patient_link_id=current_workspace.patient_link_id, practice_id=self.remote["practice_id"], patient_id=self.remote["patient_id"],
                reviewed_by="synthetic_test_driver", evidence_ref="lab:scheduling-fixture", reviewed_at=now))
            s.commit()
        self.set_fixture_grant(self.scenario != "grant_unavailable")

    def set_fixture_grant(self, permitted):
        """Explicit human fixture operation, separate from read/prepare tools."""
        with self.sessions() as s:
            previous = provider_team.read(s, self.app.box, self.app.owner)
            configuration = deepcopy(previous["configuration"])
            bot = next(bot for bot in configuration["bots"] if provider_team.bot_address(bot) == self.app.addresses["follow_up"])
            account = s.get(SchedulingAccount, self.account_id)
            if account is None:
                raise LabError("scheduling_fixture_account_missing")
            resource = team_resources.reference(self.app.box, self.app.owner, self.identity_id, "scheduling_context", account)
            prior = bot.get("resources", {}).get("allowed", [])
            bot["resources"] = {"version": 1, "allowed": [value for value in prior if value["purpose"] != "scheduling_context"] + ([{"purpose": "scheduling_context", "resource_ref": resource}] if permitted else [])}
            # The local setup gate is scoped to this scripted rehearsal/save.
            before = settings.workspace_team_setup_enabled
            settings.workspace_team_setup_enabled = True
            try:
                rehearsal = team_setup.rehearsal(s, self.app.box, self.app.owner, self.identity_id,
                    expected=previous["revision"], configuration=configuration, contract=4)
                result = provider_team.save(s, self.app.box, self.app.owner, expected=previous["revision"],
                    key="scheduling-fixture-grant-" + str(uuid4()), configuration=configuration,
                    setup_review=rehearsal["setup_review"], external_identity_id=self.identity_id, team_contract=4)
            finally:
                settings.workspace_team_setup_enabled = before
        self.app.team_revision = result["revision"]
        for member in result["members"]:
            role = member["role"]
            if role in self.app.agents and member["agent_id"] == self.app.agents[role]:
                self.app.addresses[role] = member.get("instance_id", role)

    def _reauthenticate(self, role):
        self.app.check_agent(role)
        self.app.check_agent("follow_up")

    def _bot(self):
        return CaptureBotSelection(address=self.app.addresses["follow_up"], team_revision=self.app.team_revision)

    def _context(self, s, role):
        return workspace_appointments._current(s, *self.scope, self.identity_id, self._bot(), lambda: self._reauthenticate(role))

    def _bindings(self, context):
        return {"account_id": context[0], "patient_mapping_id": context[1], "selection": context[2].model_dump(mode="json"),
                "grant_agent_id": context[3], "resource_ref": context[7], "team_revision": self.app.team_revision}

    def _broker(self, role):
        self._reauthenticate(role)
        return {"authority": BROKER_AUTHORITY, "requested_by_role": role, "requested_by_agent_id": self.app.agent_id(role),
                "grant_role": "follow_up", "grant_agent_id": self.app.agent_id("follow_up"),
                "owner_scope_id": self.app.owner, "synthetic_only": True, "external_calls": 0, "simulated_receiver_calls": len(self.calls)}

    def call(self, role, name, arguments):
        if name not in SCHEDULING_SCHEMAS:
            raise LabError("unknown_tool")
        if role not in SCHEDULING_TOOL_ROLES[name]:
            raise LabError("scheduling_tool_role_denied")
        self._reauthenticate(role)
        try:
            request = SCHEDULING_SCHEMAS[name][0].model_validate(arguments)
        except (ValidationError, ValueError, TypeError):
            raise LabError("invalid_tool_arguments") from None
        result = getattr(self, name)(role, request)
        result["broker"] = self._broker(role)
        return result

    def scheduling_read_availability(self, role, request):
        self.observations.pop(role, None)
        with self.sessions() as s:
            initial = self._context(s, role)
            result = workspace_scheduling.read_availability(s, box=self.app.box, owner=self.app.owner,
                external_identity_id=self.identity_id, workspace_id=self.app.workspace, bot=self._bot(), window=self.window,
                port=self.port, reauthenticate=lambda: self._reauthenticate(role))
            receipt = self.port.last_availability
            if receipt is None:
                raise LabError("scheduling_availability_receipt_missing")
            current = self._context(s, role)
            if current != initial:
                raise LabError("scheduling_observation_changed")
            revision = workspace.read(s, *self.scope)["revision"]
        zone, prefix = ZoneInfo(request.timezone), "ny" if request.timezone == "America/New_York" else "utc"
        slots, bound_slots = [], {}
        for index, raw in enumerate(result["slots"], 1):
            slot = AvailabilitySlot.model_validate(raw)
            ref = f"slot-{prefix}-{index}"
            bound_slots[ref] = slot
            slots.append({"slot_ref": ref, **slot.model_dump(mode="json"),
                "local_starts_at": slot.starts_at.astimezone(zone).isoformat(), "local_ends_at": slot.ends_at.astimezone(zone).isoformat()})
        self.observations[role] = {"context": current, "team_revision": self.app.team_revision, "workspace_revision": revision,
            "valid_until": datetime.fromisoformat(result["valid_until"]), "slots": bound_slots, "timezone": request.timezone,
            "google": (str(receipt.google.connection_id), receipt.google.connected_at.isoformat())}
        return {"workspace_id": self.app.workspace, "workspace_revision": revision,
            "availability": {**result, "timezone": request.timezone, "slots": slots}, "source_bindings": self._bindings(current),
            "availability_receipt_sha256": payload_hash(receipt.model_dump(mode="json")),
            "next_action": "select an observed slot and prepare a private proposal", "appointment_saved": False}

    @staticmethod
    def _proposal_ref(ticket_id):
        return "appointment-" + payload_hash({"domain": "lab-scheduling-ref.v1", "ticket_id": ticket_id})[:16]

    def _prepared(self, detail):
        if detail["appointment_saved"]:
            next_action = "inspect separate calendar state"
        elif detail["state"] == "rejected":
            next_action = "retain rejected proposal; no approval or submission is permitted"
        elif detail["dispatch_started"]:
            next_action = "human explicitly reconciles the same operation; do not resubmit"
        elif datetime.now(UTC) >= datetime.fromisoformat(detail["intent"]["expires_at"]):
            next_action = "retain expired proposal; read fresh availability before preparing a new exact intent with a new key"
        elif detail["operation_id"] is not None:
            next_action = "human may submit the exact approved operation"
        else:
            next_action = "human reviews exact private proposal"
        return {"proposal_ref": self._proposal_ref(detail["ticket_id"]), "detail": detail,
            "next_action": next_action,
            "done_when": {"appointment": "verified durable appointment receipt", "calendar": "separate calendar_state synced receipt"}}

    def scheduling_prepare_observed(self, role, request):
        command = request.model_dump(mode="json")
        saved = self.preparations.get((role, request.idempotency_key))
        if saved is not None:
            if saved["command"] != command:
                raise workspace.WorkspaceError("idempotency_conflict")
            with self.sessions() as s:
                if self._bindings(self._context(s, role)) != saved["bindings"]:
                    raise LabError("scheduling_observation_changed")
                detail = workspace_appointments.prepare(s, box=self.app.box, owner=self.app.owner,
                    workspace_id=self.app.workspace, external_identity_id=self.identity_id, body=saved["body"],
                    availability_port=self.port, appointment_port=self.port, reauthenticate=lambda: self._reauthenticate(role))
            return self._prepared(detail)
        observed = self.observations.get(role)
        if observed is None or request.slot_ref not in observed["slots"]:
            raise LabError("scheduling_observed_slot_required")
        if datetime.now(UTC) >= observed["valid_until"]:
            raise LabError("scheduling_observed_slot_expired")
        if self.app.team_revision != observed["team_revision"]:
            raise LabError("scheduling_observation_changed")
        with self.sessions() as s:
            context = self._context(s, role)
            if context != observed["context"]:
                raise LabError("scheduling_observation_changed")
            revision = workspace.read(s, *self.scope)["revision"]
            if revision != request.expected_workspace_revision or revision != observed["workspace_revision"]:
                raise workspace.WorkspaceError("revision_conflict")
            body = AppointmentPrepare(bot=self._bot(), action="book", slot=observed["slots"][request.slot_ref], share=True, idempotency_key=request.idempotency_key)
            self.port.expected_google = observed["google"]
            try:
                detail = workspace_appointments.prepare(s, box=self.app.box, owner=self.app.owner,
                    workspace_id=self.app.workspace, external_identity_id=self.identity_id, body=body,
                    availability_port=self.port, appointment_port=self.port, reauthenticate=lambda: self._reauthenticate(role))
            finally:
                self.port.expected_google = None
        self.preparations[(role, request.idempotency_key)] = {"command": command, "body": body, "bindings": self._bindings(context)}
        if self.lost_prepare_reply:
            self.lost_prepare_reply = False
            raise LabError("injected_lost_scheduling_prepare_reply")
        return self._prepared(detail)

    def scheduling_list_proposals(self, role, request):
        with self.sessions() as s:
            context = self._context(s, role)
            catalog = appointment_work.catalog(s, *self.scope)
            items, retained = [], {}
            for summary in catalog["items"]:
                detail = appointment_work.read(s, *self.scope, summary["ticket_id"])
                source = s.get(AppointmentWork, summary["ticket_id"])
                if source is None:
                    raise LabError("scheduling_proposal_unavailable")
                ref = self._proposal_ref(summary["ticket_id"])
                if ref in retained:
                    raise LabError("scheduling_proposal_ref_collision")
                item = {**summary, "proposal_ref": ref, "revision_id": detail["revision_id"], "payload_hash": detail["payload_hash"],
                    "appointment_saved": detail["appointment_saved"], "calendar_state": detail["calendar_state"],
                    "source_bindings": {"account_id": source.account_id, "patient_mapping_id": source.patient_mapping_id,
                        "selection": detail["intent"]["selection"]}}
                items.append(item)
                retained[ref] = deepcopy(item)
        observed_at = datetime.now(UTC)
        self.catalog_reads[role] = {"items": retained, "observed_at": observed_at, "bindings": self._bindings(context)}
        return {"catalog": {**catalog, "items": items, "has_more": catalog["next_cursor"] is not None, "observed_at": observed_at.isoformat()},
            "source_bindings": self._bindings(context)}

    def scheduling_inspect_prepared(self, role, request):
        observed = self.catalog_reads.get(role)
        if observed is None or request.proposal_ref not in observed["items"]:
            raise LabError("scheduling_listed_proposal_required")
        if datetime.now(UTC) - observed["observed_at"] > timedelta(seconds=60):
            raise LabError("scheduling_proposal_list_expired")
        item = observed["items"][request.proposal_ref]
        with self.sessions() as s:
            if self._bindings(self._context(s, role)) != observed["bindings"]:
                raise LabError("scheduling_observation_changed")
            detail = appointment_work.read(s, *self.scope, item["ticket_id"])
            if any(detail[key] != item[key] for key in ("ticket_id", "revision_id", "payload_hash")) or detail["intent"]["selection"] != item["source_bindings"]["selection"]:
                raise LabError("scheduling_proposal_binding_changed")
        return self._prepared(detail)

    def human_execute(self, ticket_id, *, authorized=False, mode="submit"):
        """Separate test driver; never registered or accessible from MCP/tools."""
        if authorized is not True:
            raise LabError("scripted_human_authorization_required")
        if mode not in {"submit", "reconcile"}:
            raise LabError("unsupported_scheduling_test_driver_mode")
        with self.sessions() as s:
            source = s.get(AppointmentWork, ticket_id)
            if source is None or source.workspace_id != self.app.workspace or source.box_id != self.app.box or source.owner_id != self.app.owner:
                raise LabError("scheduling_proposal_scope_mismatch")
            detail = appointment_work.read(s, *self.scope, ticket_id)
            if detail["operation_id"] is None:
                if mode != "submit":
                    raise LabError("scheduling_dispatch_required")
                detail = appointment_work.decide(s, *self.scope, ticket_id, external_identity_id=self.identity_id,
                    revision_id=detail["revision_id"], digest=detail["payload_hash"], choice="approve")
            result = appointment_execution.run(s, *self.scope, ticket_id, external_identity_id=self.identity_id,
                reauthenticate=lambda: workspace.read(s, *self.scope), port=self.port, operation_id=detail["operation_id"],
                revision_id=detail["revision_id"], digest=detail["payload_hash"], mode=mode)
        return self._prepared(result)

    def _respond(self, request):
        if request.url.host != "scheduling.example.invalid":
            raise LabError("unexpected_scheduling_receiver_origin")
        path, params = request.url.path, request.url.params
        self.calls.append({"method": request.method, "path": path})
        if path.endswith("/availability/verified") and request.method == "GET":
            if self.scenario == "unavailable":
                return httpx.Response(503)
            start, end = datetime.fromisoformat(params["from"]), datetime.fromisoformat(params["to"])
            slots = [slot.model_dump(mode="json") for slot in self.slots if start <= slot.starts_at and slot.ends_at <= end]
            if self.scenario == "stale_slot" and end - start < timedelta(hours=1):
                slots = []
            now = datetime.now(UTC)
            payload = {"contract_version": "1", "request_nonce": params["requestNonce"],
                **{key: self.remote[key] for key in ("practice_id", "actor_id", "practitioner_id", "location_id", "appointment_type_id")},
                "range_start": start.isoformat(), "range_end": end.isoformat(), "slots": slots,
                "google": {"provider": "google", "calendar_id": "primary", "connection_id": self.remote["connection_id"],
                    "connected_at": self.connected_at.isoformat(), "checked_at": now.isoformat()}}
        elif path == "/v1/appointment-operations" and request.method == "POST":
            body = json.loads(request.content)
            operation_id = body["operation_id"]
            if operation_id in self.journal:
                raise LabError("synthetic_duplicate_appointment_submission")
            snapshot = {"id": str(uuid4()), "version": 1, "status": "booked", "client_id": None,
                **{key: body[key] for key in ("patient_id", "practitioner_id", "location_id", "appointment_type_id")}, **body["slot"]}
            self.journal[operation_id] = {"operation_id": operation_id, "request_hash": payload_hash({"practice_id": self.remote["practice_id"], "request": body}), "appointment": snapshot}
            payload = self.journal[operation_id]
            if self.lost_submit_reply:
                self.lost_submit_reply = False
                raise httpx.ReadTimeout("injected lost Scheduling save response")
        elif path.startswith("/v1/appointment-operations/") and request.method == "GET":
            operation_id = path.rsplit("/", 1)[1]
            if operation_id not in self.journal:
                return httpx.Response(404)
            payload = self.journal[operation_id]
        else:
            raise LabError("unexpected_scheduling_receiver_route")
        if "/appointment-operations" in path:
            payload = {**payload, "contract_version": "1", "request_nonce": params["requestNonce"],
                "practice_id": self.remote["practice_id"], "actor_id": self.remote["actor_id"],
                "checked_at": datetime.now(UTC).isoformat(), "calendar_state": self.calendar_state}
        return httpx.Response(200, headers={"content-type": "application/json", "cache-control": "no-store"},
            stream=httpx.ByteStream(json.dumps(payload).encode()))
