"""Fixed-role connector tools shared by the model lab and optional MCP profile.

This executes adapter boundaries, not entire qualifications. Fixtures are set
up by a synthetic provider before exposing tools. No tool can grant access,
review a note, approve a proposal or submit an external action.
"""

from contextlib import ExitStack
from typing import Literal

from pydantic import Field, ValidationError

from cosmas_os.application.workspace import WorkspaceError
from cosmas_os.ports.vendor_artifacts import ArtifactStoreError
from lab import account_tools
from lab.engine import SCHEMAS, Arguments, SaveArgs, World
from lab.fax_tools import FAX_SCHEMAS, FAX_TOOL_ROLES, FaxTools
from lab.inbox_tools import INBOX_SCHEMAS, INBOX_TOOL_ROLES, InboxTools
from lab.research_tools import RESEARCH_SCHEMAS, RESEARCH_TOOL_ROLES, ResearchTools
from lab.scheduling_tools import SCHEDULING_SCHEMAS, SCHEDULING_TOOL_ROLES, SchedulingTools
from lab.store import LabError


class SourceReference(Arguments):
    source_ref: str = Field(pattern=r"^source-[1-9][0-9]*$")


class DraftReference(Arguments):
    role: Literal["chief", "scribe", "visit_prep", "research", "follow_up"]


class CompactDraft(Arguments):
    body: str = Field(min_length=10, max_length=4000)
    source_refs: list[str] = Field(min_length=1, max_length=8)
    dependency_roles: list[Literal["chief", "scribe", "visit_prep", "research", "follow_up"]] = Field(max_length=5)


TEAM_SCHEMAS = {
    "read_selected_source": (SourceReference, "Read an exact saved source using the short source_ref returned by list_sources. Actual immutable IDs remain in the receipt."),
    "read_shared_draft": (DraftReference, "Read a currently shared draft by its role. The server verifies and records its exact hash; no draft may be cited without this read."),
    "save_connector_draft": (CompactDraft, "Save your private draft using short source_refs you actually read and dependency_roles whose exact shared drafts you read. The server binds the original IDs/hashes; no implicit read, review or send occurs."),
}
TEAM_ROLES = frozenset({"chief", "scribe", "visit_prep", "research", "follow_up"})
CONNECTOR_SCHEMAS = {**account_tools.ACCOUNT_SCHEMAS, **FAX_SCHEMAS, **RESEARCH_SCHEMAS, **TEAM_SCHEMAS,
                     **INBOX_SCHEMAS, **SCHEDULING_SCHEMAS}
CONNECTOR_ROLES = {**account_tools.ACCOUNT_TOOL_ROLES, **FAX_TOOL_ROLES, **RESEARCH_TOOL_ROLES,
                   **{name: TEAM_ROLES for name in TEAM_SCHEMAS}, **INBOX_TOOL_ROLES, **SCHEDULING_TOOL_ROLES}
ALL_SCHEMAS = {**SCHEMAS, **CONNECTOR_SCHEMAS}
WRITES = {"save_artifact", "delegate_team", "account_save_selected_observations", "fax_prepare",
          "fax_prepare_ready", "account_select_observed_items", "research_lookup_trials", "research_save_selection", "save_connector_draft",
          "google_inbox_select_message", "google_inbox_prepare_review", "scheduling_prepare_observed"}


def visible(role, name):
    if name in CONNECTOR_ROLES:
        return role in CONNECTOR_ROLES[name]
    return name in SCHEMAS and (role == "chief" or name != "delegate_team")


class ConnectorWorld(World):
    schemas = ALL_SCHEMAS
    max_tool_calls_per_turn = 12
    tool_scope = ("Only offline, invented-data account/research observations, metadata-review drafts and private fax/appointment proposals are available. "
                  "There are no recording, permission, approval, sending, booking or payment tools. ")
    extra_instructions = (
        "Use application_status.workspace_revision before a save. On workspace_revision_conflict read current status and "
        "retry the same selected content with a new key/current revision. Account read receipts alone are not shared evidence: "
        "use account_select_observed_items with the original read_key and selected item IDs, then read_source the saved entry before citing it. "
        "Every connector source is invented. Fax pending_approval/acceptance not_observed is a proposal, not delivery. "
        "Prefer read_selected_source using list_sources.source_ref and read_shared_draft using its role. "
        "Prefer save_connector_draft with source_refs and dependency_roles. The server binds exact hashes, so do not copy UUIDs/hashes. "
        "These compact tools satisfy read_source/read_artifact/save_artifact requirements. "
        "Use proposal_ids from fax_readiness rather than inventing operation UUIDs. "
        "A failed source read is unavailable, not an empty result or evidence of absence. ")
    jobs = {
        "chief": "Read original sources, delegate visit_prep, scribe and research together in ONE call, then delegate follow_up. "
            "Read all shared artifacts and the saved connector evidence before saving a concise synthesis. Verify the Documo "
            "proposal remains unsubmitted by fax_list_proposals then fax_receipt, selected Google observations reached Prep, "
            "and selected trial evidence reached Research. Do not create a second fax proposal. "
            "Include follow_up as an exact dependency. Report human review and missing DOB explicitly.",
        "visit_prep": "Read the original synthetic encounter. Read Google mail headers and next-seven-day calendar using separate "
            "stable retry keys. Use account_select_observed_items with the ORIGINAL read_key to save one selected mail item, then "
            "read current application_status before saving one calendar item with its own original read_key. Read both saved sources before citing them. "
            "Save your private preparation draft "
            "with all read source IDs. Header metadata is not a message body and calendar data does not establish patient matching or consent.",
        "research": "Read the original encounter. Use research_lookup_trials for the synthetic provider's fixed reviewed cardiac-trial "
            "query; use current workspace revision. Select the FIRST returned source hash only and save it with research_save_selection. "
            "Read that exact workspace evidence before saving your research draft. Retain conditions, recruiting/site conflict and "
            "uncertainty: trial staff must assess eligibility; cell therapy benefit is unestablished. Do not recommend treatment.",
        "scribe": "Read the supplied typed encounter and draft a concise source-faithful summary. DOB is missing and remains optional; "
            "do not invent it or claim audio was recorded. Share the saved draft with Chief and Follow-up.",
        "follow_up": "Read all three saved upstream artifacts by exact ID/hash and original sources. Call fax_readiness for documo. "
            "Use returned source/document/connection/correspondence, proposal_ids.fax and current revision to fax_prepare an exact "
            "private administrative proposal. Read fax_receipt using summary ticket/id/version/revision/hash and a new read key. "
            "Do NOT request refresh on an unsubmitted proposal. Save your draft with all three dependencies and exact source IDs; "
            "state pending human review, dispatch not_started, acceptance not_observed and no delivery. Do not ask for human approval inside the agent tools.",
    }

    def __init__(self, *args, prepare_fax=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.fixtures = ExitStack()
        try:
            # Reviewed synthetic Scheduling grants precede all account reads.
            # Startup may advance the team revision; no tool may grant itself access.
            self.scheduling = SchedulingTools(self.app, self.store.root / (self.episode + "-scheduling"))
            self.fixtures.callback(self.scheduling.close)
            self.fixtures.enter_context(account_tools.prepared_account_sandboxes(self.app))
            self.inbox = InboxTools(self.app, self.store, self.episode)
            self.fax = None
            if prepare_fax:
                self.prepare_fax_fixture()
            self.research = ResearchTools(self.app)
        except BaseException:
            self.fixtures.close()
            raise

    def close(self):
        self.fixtures.close()

    def prepare_fax_fixture(self):
        """Scripted provider setup only; never a registered/model-callable tool."""
        if self.fax is not None:
            raise LabError("fax_fixture_already_prepared")
        self.fax = FaxTools(self.app, self.store.root / (self.episode + "-fax-artifacts"))
        self.fixtures.callback(self.fax.close)
        self.event("simulated_provider", "fax_fixture_reviewed", authority="scripted_synthetic_source_review_only")

    def tool_visible(self, role, name):
        return visible(role, name)

    def source_references(self):
        if not hasattr(self, "source_refs"):
            self.source_refs = {}
        for source in self.app.sources(metadata_only=True):
            if source["id"] not in self.source_refs.values():
                self.source_refs["source-" + str(len(self.source_refs) + 1)] = source["id"]
        return self.source_refs

    def source_reference(self, identifier):
        return next(key for key, value in self.source_references().items() if value == identifier)

    def model_tools(self, role):
        """Offer exact allowed choices; authority still rechecks at execution.

        Schema choices avoid transcription mistakes in long hashes and IDs.
        They never read accounts, save selections or perform implicit retries.
        """
        tools = [tool for tool in super().model_tools(role) if tool["function"]["name"] not in {
            "read_source", "read_artifact", "save_artifact", "account_save_selected_observations",
            "fax_prepare", "fax_receipt"}]
        sources = [source["id"] for source in self.app.sources(metadata_only=True)]
        references = self.source_references()
        reads = [self.store.read(self.episode + ":accounts", item["id"], role, item["sha256"])
                 for item in self.store.visible(self.episode + ":accounts", role)]
        artifacts = self.store.visible(self.episode, role)
        for tool in tools:
            function = tool["function"]
            schema = function["parameters"]
            fields = schema["properties"]
            if function["name"] == "read_source" and sources:
                fields["source_id"]["enum"] = sources
            elif function["name"] == "read_selected_source":
                fields["source_ref"]["enum"] = list(references)
            elif function["name"] == "save_connector_draft":
                fields["source_refs"]["items"]["enum"] = list(references)
            elif function["name"] == "save_artifact":
                if sources:
                    fields["source_ids"]["items"]["enum"] = sources
                if artifacts:
                    definition = schema["$defs"]["ArtifactArgs"]["properties"]
                    definition["artifact_id"]["enum"] = [item["id"] for item in artifacts]
                    definition["sha256"]["enum"] = [item["sha256"] for item in artifacts]
            elif function["name"] == "read_artifact" and artifacts:
                fields["artifact_id"]["enum"] = [item["id"] for item in artifacts]
                fields["sha256"]["enum"] = [item["sha256"] for item in artifacts]
            elif function["name"] == "account_select_observed_items" and reads:
                fields["read_key"]["enum"] = [item["request"]["idempotency_key"] for item in reads]
                identifiers = sorted({v["id"] for item in reads for v in item["observation"]["items"]})
                if identifiers:
                    fields["item_ids"]["items"]["enum"] = identifiers
            elif function["name"] == "account_save_selected_observations" and reads:
                fields["observation_id"]["enum"] = [item["id"] for item in reads]
                fields["observation_sha256"]["enum"] = [item["sha256"] for item in reads]
                identifiers = sorted({v["id"] for item in reads for v in item["observation"]["items"]})
                if identifiers:
                    fields["item_ids"]["items"]["enum"] = identifiers
        return tools

    def _execute(self, role, name, args):
        if not visible(role, name):
            raise LabError("tool_not_available_for_role")
        values = args.model_dump(mode="json", exclude_none=True)
        try:
            if name == "read_selected_source":
                source_id = self.source_references().get(args.source_ref)
                if source_id is None:
                    raise LabError("source_outside_selected_encounter")
                source = self._execute(role, "read_source", SCHEMAS["read_source"][0](source_id=source_id))
                return {**source, "source_ref": args.source_ref}
            if name == "read_shared_draft":
                artifact = next((a for a in self.store.visible(self.episode, role) if a["role"] == args.role), None)
                if artifact is None:
                    raise LabError("artifact_not_shared_with_this_agent")
                return self._execute(role, "read_artifact", SCHEMAS["read_artifact"][0](artifact_id=artifact["id"], sha256=artifact["sha256"]))
            if name == "save_connector_draft":
                references = self.source_references()
                if any(ref not in references for ref in args.source_refs):
                    raise LabError("source_outside_selected_encounter")
                dependencies = []
                for recipient in args.dependency_roles:
                    sha = self.artifact_reads[role].get(recipient)
                    if sha is None:
                        raise LabError("unread_or_stale_dependency")
                    dependencies.append({"artifact_id": recipient, "sha256": sha})
                return self._execute(role, "save_artifact", SaveArgs(body=args.body,
                    source_ids=[references[ref] for ref in args.source_refs], dependencies=dependencies,
                    share_with=["chief", "follow_up"]))
            if name in account_tools.ACCOUNT_SCHEMAS:
                result = account_tools.execute(self.app, self.store, self.episode, role, name, values)
                if "error" in result:
                    raise LabError(result["error"])
                if result.get("entry_id"):
                    result["source_ref"] = self.source_reference(result["entry_id"])
                return result
            if name in FAX_SCHEMAS:
                if self.fax is None:
                    raise LabError("fax_fixture_provider_review_required")
                return self.fax.call(role, name, values)
            if name in RESEARCH_SCHEMAS:
                result = self.research.call(role, name, values)
                if result["result"].get("entry_id"):
                    result["source_ref"] = self.source_reference(result["result"]["entry_id"])
                return result
            if name in INBOX_SCHEMAS:
                result = self.inbox.call(role, name, values)
                if "error" in result:
                    raise LabError(result["error"])
                if name == "google_inbox_select_message" and result.get("entry_id"):
                    result["source_ref"] = self.source_reference(result["entry_id"])
                return result
            if name in SCHEDULING_SCHEMAS:
                return self.scheduling.call(role, name, values)
            result = super()._execute(role, name, args)
            if name == "list_sources" and isinstance(result, list):
                refs = {value: key for key, value in self.source_references().items()}
                result = [{**source, "source_ref": refs[source["id"]]} for source in result]
            if name == "application_status" and isinstance(result, dict):
                from sqlalchemy.orm import Session

                from cosmas_os.application import workspace

                with Session(self.app.engine) as session:
                    snapshot = workspace.read(session, self.app.box, self.app.owner, self.app.workspace)
                result = {**result, "workspace_revision": snapshot["revision"],
                          "connector_transport": "offline_http_twin", "human_review_available_as_tool": False}
            return result
        except WorkspaceError as error:
            raise LabError(error.code) from None
        except (ArtifactStoreError, ValidationError):
            raise LabError("connector_source_or_arguments_unavailable") from None
