"""Google metadata-only private draft tools; human F8 review is never a tool."""

from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from cosmas_os.adapters.google_inbox import GoogleInboxMetadata
from cosmas_os.application import google_inbox, provider_team, shared_work, workspace
from cosmas_os.models import Principal, WorkspaceEntry
from lab.account_tools import _binding, _box, _current_binding, _stored_read
from lab.store import LabError, digest


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Key(Arguments):
    idempotency_key: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._-]+$")


class SelectMessage(Key):
    read_key: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._-]+$")
    message_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    expected_workspace_revision: int = Field(ge=1, le=500)


class PrepareReview(Key):
    selection_key: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._-]+$")
    expected_workspace_revision: int = Field(ge=1, le=500)


class ReviewStatus(Arguments):
    review_key: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._-]+$")


INBOX_SCHEMAS = {
    "google_inbox_read_headers": (Key, "Read up to 10 synthetic Google Subject/From headers through the real connected-account adapter. Reuse the same key after a lost reply. No body, attachments, clinical triage, read-label mutation or new grant."),
    "google_inbox_select_message": (SelectMessage, "Explicitly select one exact message from your ORIGINAL read_key into real workspace evidence at the current revision. Metadata remains incomplete and needs_human. Reuse the exact key for lost-reply recovery."),
    "google_inbox_prepare_review": (PrepareReview, "Save a private metadata-only administrative-review draft using your ORIGINAL select-message idempotency_key as selection_key. The server resolves the exact saved evidence without a provider read. No F8 approval, clinical priority, assignment, full-message review or send occurs. Keep this original idempotency_key as review_key."),
    "google_inbox_list_reviews": (Arguments, "List existing Google metadata-review drafts in this workspace with their original review_key. No new provider read, review, assignment or completion occurs."),
    "google_inbox_review_status": (ReviewStatus, "Read persisted private draft and separate scripted-human metadata-only F8 handoff status using its original review_key. Responsibility offers need explicit human acceptance; a handoff does not complete triage."),
}
INBOX_TOOL_ROLES = {name: frozenset({"chief", "follow_up"}) for name in INBOX_SCHEMAS}
BASE = {"synthetic_only": True, "provider_transport": "offline_http_twin", **google_inbox.FLAGS}


class InboxTools:
    def __init__(self, app, store, episode):
        self.app, self.store, self.episode = app, store, episode
        self.box = _box(app, "google")  # Already connected only by the human fixture.
        self.adapter = GoogleInboxMetadata(self.box.service, self.box.identity)
        # Explicit test-driver fixture, never a registered setup/assignment tool.
        self.reviewer_id = str(uuid4())
        with Session(app.engine) as session:
            session.add(Principal(id=self.reviewer_id, box_id=app.box, principal_type="human",
                display_name="Synthetic Inbox Nurse", state="active"))
            session.commit()

    def _authorize(self, session, role):
        app = self.app
        _, bot, _ = provider_team.active_bot(session, app.box, app.owner,
            app.addresses[role], app.team_revision)
        if bot.agent_id != app.agent_id(role):
            raise LabError("agent_identity_changed")
        return _binding(self.box, session)

    def _read_id(self, role, key):
        return "google-inbox-read-" + digest([self.app.box, self.app.workspace, role, key])

    def _read(self, role, args):
        with Session(self.app.engine) as session:
            binding = self._authorize(session, role)
        identifier = self._read_id(role, args["idempotency_key"])
        saved = _stored_read(self.store, self.episode + ":google-inbox", identifier, role)
        request = {"tool": "google_inbox_read_headers", **args}
        if saved is None:
            observed = self.adapter.read()
            with Session(self.app.engine) as session:
                if self._authorize(session, role) != binding:
                    raise LabError("google_inbox_account_changed")
                w = workspace.read(session, self.app.box, self.app.owner, self.app.workspace)
            saved = self.store.save(self.episode + ":google-inbox", identifier,
                {"request": request, "requester_role": role, "requester_agent_id": self.app.agent_id(role),
                 "team_revision": self.app.team_revision, "workspace_id": self.app.workspace,
                 "box_id": self.app.box, "workspace_revision": w["revision"],
                 "account_binding_sha256": binding, "observation": observed, "share_with": [role]})
            replay = False
        else:
            self._check_read(saved, role, binding)
            if saved["request"] != request:
                raise LabError("google_inbox_read_idempotency_conflict")
            replay = True
        with Session(self.app.engine) as session:
            if self._authorize(session, role) != binding:
                raise LabError("google_inbox_account_changed")
        return {**BASE, "status": "ready" if saved["observation"]["items"] else "empty",
            "read_key": args["idempotency_key"], "observation": saved["observation"],
            "read_receipt_sha256": saved["sha256"], "workspace_revision": saved["workspace_revision"],
            "saved_to_workspace": False, "idempotent_replay": replay,
            "next_action": "Select one exact observed message ID to save metadata evidence. Full-message clinical triage remains unavailable."}

    def _check_read(self, saved, role, binding):
        app = self.app
        if (saved["requester_role"] != role or saved["requester_agent_id"] != app.agent_id(role)
                or saved["team_revision"] != app.team_revision or saved["workspace_id"] != app.workspace
                or saved["box_id"] != app.box):
            raise LabError("google_inbox_read_scope_mismatch")
        if saved["account_binding_sha256"] != binding:
            raise LabError("google_inbox_account_changed")

    def _draft(self, session, role, review_key):
        # Explicitly shared within this fixed workspace; Chief can inspect a
        # Follow-up draft, but may not reuse that role's private provider read.
        app = self.app
        candidates = ["google-inbox-draft-" + digest([self.episode, r, review_key])[:64]
                      for r in INBOX_TOOL_ROLES["google_inbox_prepare_review"]]
        rows = list(session.scalars(select(WorkspaceEntry).where(WorkspaceEntry.workspace_id == app.workspace,
            WorkspaceEntry.box_id == app.box, WorkspaceEntry.idempotency_key.in_(candidates))))
        if len(rows) != 1:
            raise LabError("google_inbox_review_key_unavailable")
        return rows[0]

    def _invoke(self, role, name, args):
        app = self.app
        if name == "google_inbox_read_headers":
            with self.store.lock:
                return self._read(role, args)
        with Session(app.engine) as session:
            binding = self._authorize(session, role)
            if name == "google_inbox_select_message":
                saved = self.store.read(self.episode + ":google-inbox", self._read_id(role, args["read_key"]), role)
                self._check_read(saved, role, binding)
                return google_inbox.select_message(session, app.box, app.owner, app.workspace,
                    expected=args["expected_workspace_revision"], key="google-inbox-select-" + digest([self.episode, role, args["idempotency_key"]])[:64],
                    captured=saved, message_id=args["message_id"], binding=binding)
            if name == "google_inbox_prepare_review":
                selected = session.scalar(select(WorkspaceEntry).where(
                    WorkspaceEntry.workspace_id == app.workspace, WorkspaceEntry.box_id == app.box,
                    WorkspaceEntry.idempotency_key == "google-inbox-select-" + digest([self.episode, role, args["selection_key"]])[:64]))
                if selected is None:
                    raise LabError("google_inbox_selection_key_unavailable")
                result = google_inbox.prepare(session, app.box, app.owner, app.workspace,
                    entry_id=selected.id, expected=args["expected_workspace_revision"],
                    key="google-inbox-draft-" + digest([self.episode, role, args["idempotency_key"]])[:64],
                    review_key=args["idempotency_key"], requester_role=role, episode=self.episode, binding=binding)
                return {**result, "review_key": args["idempotency_key"]}
            if name == "google_inbox_review_status":
                row = self._draft(session, role, args["review_key"])
                return {**google_inbox.status(session, app.box, app.owner, app.workspace,
                    draft_entry_id=row.id, binding=binding), "review_key": args["review_key"]}
            if name == "google_inbox_list_reviews":
                w = workspace._workspace(session, app.box, app.owner, app.workspace)
                items = []
                import json
                for record in session.scalars(select(WorkspaceEntry).where(
                        WorkspaceEntry.workspace_id == app.workspace, WorkspaceEntry.box_id == app.box,
                        WorkspaceEntry.kind == "scratchpad").order_by(WorkspaceEntry.revision)):
                    try:
                        saved = json.loads(record.content)
                    except (ValueError, TypeError):
                        continue
                    if not isinstance(saved, dict) or saved.get("schema") != google_inbox.DRAFT or saved.get("episode") != self.episode:
                        continue
                    row, _, state = google_inbox.bound_draft(session, w, record.id, binding)
                    items.append({"review_key": saved["review_key"], "draft_entry_id": row.id, "source_state": state})
                return {**BASE, "status": "ready" if items else "empty", "items": items,
                    "next_action": "Inspect a specific persisted review_key; no full-message review or completion is implied."}
        raise LabError("unknown_google_inbox_tool")

    def call(self, role, name, args):
        if name not in INBOX_SCHEMAS:
            return {**BASE, "status": "failed", "error": "unknown_google_inbox_tool"}
        if role not in INBOX_TOOL_ROLES[name]:
            return {**BASE, "status": "failed", "error": "google_inbox_tool_role_denied"}
        try:
            command = INBOX_SCHEMAS[name][0].model_validate(args).model_dump()
        except ValidationError:
            return {**BASE, "status": "failed", "error": "invalid_google_inbox_arguments"}
        try:
            self.app.check_agent(role)
            result = self._invoke(role, name, command)
            self.app.check_agent(role)
            result = {**BASE, **result}
        except (LabError, workspace.WorkspaceError) as error:
            result = {**BASE, "status": "failed", "error": str(error) if isinstance(error, LabError) else error.code,
                "next_action": "Check current account, role and source state; explicitly recover the exact request. No implicit read or grant occurred."}
        except Exception:
            result = {**BASE, "status": "failed", "error": "google_inbox_read_or_save_failed",
                "next_action": "Read unavailable; inspect account health and explicitly retry. Unavailable is not an empty inbox."}
        self.store.event(self.episode, role, "google_inbox_tool", tool=name, status=result["status"],
            error=result.get("error"), draft_entry_id=result.get("draft_entry_id"))
        return result

    execute = call

    def human_review_assign(self, draft_entry_id, *, actor_id, expected_workspace_revision,
                            idempotency_key, metadata_only_acknowledged=False, recipient_id=None):
        """Separate explicit scripted human, never exposed in tool schemas."""
        app = self.app
        binding = _current_binding(self.box)
        def ensure_current(session):
            if _binding(self.box, session) != binding:
                raise LabError("google_inbox_account_changed")
        with Session(app.engine) as session:
            ensure_current(session)
            reviewed = google_inbox.human_review(session, app.box, actor_id, app.workspace,
                draft_entry_id=draft_entry_id, expected=expected_workspace_revision,
                key=idempotency_key, metadata_only_acknowledged=metadata_only_acknowledged,
                binding=binding, ensure_current=ensure_current)
            item = reviewed["f8"]
            if item is None:
                raise LabError("google_inbox_human_f8_missing")
            ensure_current(session)
            records = item["handoffs"]
            # Exact offer retry uses the original expected version. No acceptance
            # occurs implicitly, even if the whole helper's reply was lost.
            offer_key = "google-offer-" + digest([draft_entry_id, idempotency_key])[:64]
            from cosmas_os.models import WorkHandoff
            prior = session.scalar(select(WorkHandoff).where(WorkHandoff.ticket_id == item["ticket_id"],
                WorkHandoff.actor_id == actor_id, WorkHandoff.idempotency_key == offer_key))
            shared_work.act(session, app.box, actor_id, item["ticket_id"],
                expected=prior.expected_version if prior else item["version"], revision_id=item["revision_id"],
                digest=item["payload_hash"], key=offer_key, kind="offer", recipient=recipient_id or self.reviewer_id)
            result = google_inbox.status(session, app.box, app.owner, app.workspace,
                draft_entry_id=draft_entry_id, binding=binding)
            if not records:
                app.event("simulated_provider", "google_metadata_review_and_offer", draft_entry_id=draft_entry_id,
                    actor_id=actor_id, ticket_id=item["ticket_id"], whole_message_reviewed=False)
            return {**BASE, **result, "authority": "separate_scripted_human_only"}

    def human_accept(self, draft_entry_id, *, actor_id, idempotency_key, offer_id, expected_version):
        app = self.app
        binding = _current_binding(self.box)
        with Session(app.engine) as session:
            if _binding(self.box, session) != binding:
                raise LabError("google_inbox_account_changed")
            status = google_inbox.status(session, app.box, app.owner, app.workspace,
                draft_entry_id=draft_entry_id, binding=binding)
            if status["source_state"] != "current":
                raise LabError("google_inbox_source_changed")
            item = status["f8"]
            if item is None:
                raise LabError("google_inbox_human_f8_missing")
            shared_work.act(session, app.box, actor_id, item["ticket_id"], expected=expected_version,
                revision_id=item["revision_id"], digest=item["payload_hash"], key=idempotency_key,
                kind="accept", offer_id=offer_id)
            result = google_inbox.status(session, app.box, app.owner, app.workspace,
                draft_entry_id=draft_entry_id, binding=binding)
            return {**BASE, **result, "authority": "separate_scripted_human_only"}
