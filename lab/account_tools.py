"""Role-scoped account observations, explicitly selected into workspace evidence.

Only the human test driver prepares the offline OAuth fixtures. Tools cannot
connect accounts, add permissions, send mail, or change calendars. The existing
adapters own credentials and authority checks; the lab store owns immutable read
receipts, while the application workspace owns selected evidence and revisions.
"""

import hashlib
import json
from contextlib import contextmanager
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from cosmas_os.application import provider_team, workspace
from cosmas_os.models import ExternalIdentity, WorkspaceEntry
from lab.mail_sandbox import MailSandbox
from lab.store import LabError, digest

ACCOUNT_ROLES = frozenset({"chief", "visit_prep", "inbox", "follow_up"})


class AccountArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class AccountStatus(AccountArguments):
    provider: Literal["google", "microsoft"]


class AccountRead(AccountStatus):
    idempotency_key: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._-]+$")


class SaveSelectedObservations(AccountArguments):
    observation_id: str = Field(min_length=1, max_length=100)
    observation_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    item_ids: list[str] = Field(min_length=1, max_length=25)
    expected_workspace_revision: int = Field(ge=1, le=500)
    idempotency_key: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._-]+$")


class SelectObservedItems(AccountArguments):
    read_key: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._-]+$")
    item_ids: list[str] = Field(min_length=1, max_length=25)
    expected_workspace_revision: int = Field(ge=1, le=500)
    idempotency_key: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._-]+$")


ACCOUNT_SCHEMAS = {
    "account_connection_status": (AccountStatus, "Check the selected synthetic account's connection health; this does not read inbox/calendar data or grant access."),
    "account_read_mail_headers": (AccountRead, "Read bounded synthetic inbox headers through the real Google/Microsoft adapter. Reuse the exact key after a lost response; headers do not prove message-body contents."),
    "account_read_calendar": (AccountRead, "Read seven days of bounded synthetic calendar summaries through the real adapter. Reuse the exact key after a lost response; this does not book or confirm an encounter."),
    "account_save_selected_observations": (SaveSelectedObservations, "Explicitly save selected items from an exact read receipt into this workspace's real evidence. Requires the read hash, item IDs, current workspace revision and an exact retry key. This does not approve clinical work or an external action."),
    "account_select_observed_items": (SelectObservedItems, "Save selected item IDs using the ORIGINAL account read idempotency key. The server resolves and verifies the exact immutable read and source hashes; no new provider read occurs. Requires the current workspace revision and a stable save retry key; does not approve or send."),
}
ACCOUNT_TOOL_ROLES = {name: ACCOUNT_ROLES for name in ACCOUNT_SCHEMAS}

LIMITS = {
    "mail": "Inbox metadata only: up to 10 Google or 25 Microsoft headers; no message bodies or attachments.",
    "calendar": "Next seven days, up to 25 calendar summaries; no scheduling writes or inferred patient/encounter match.",
}
BASE_RECEIPT = {
    "synthetic_only": True,
    "provider_transport": "offline_http_twin",
    "external_effects": 0,
    "clinical_approval": False,
}


@contextmanager
def prepared_account_sandboxes(app, providers=("google", "microsoft")):
    """Test-driver setup only: real OAuth/key custody against invented responses.

    Deliberately absent from ACCOUNT_SCHEMAS. Runtime tools receive only accounts
    already prepared and selected by this synthetic human fixture.
    """
    if getattr(app, "account_tool_sandboxes", None) is not None:
        raise LabError("account_sandboxes_already_prepared")
    boxes = {}
    app.account_tool_sandboxes = boxes
    try:
        for provider in providers:
            box = MailSandbox(app, provider)
            boxes[provider] = box
            # The older single-provider fixture uses one issuer for each app.
            # Distinct selected provider identities must respect the real
            # issuer/org/principal uniqueness constraint when prepared together.
            with box.factory() as session:
                identity = session.get(ExternalIdentity, box.account)
                if identity is None:
                    raise LabError("synthetic_account_missing")
                identity.issuer = f"https://{provider}.identity.example.invalid"
                session.commit()
            box.connect()
        yield boxes
    finally:
        for box in boxes.values():
            box.close()
        del app.account_tool_sandboxes


def _box(app, provider):
    box = getattr(app, "account_tool_sandboxes", {}).get(provider)
    if (box is None or box.app is not app or box.provider != provider
            or (box.identity.box_id, box.identity.principal_id) != (app.box, app.owner)):
        raise LabError("account_connection_unavailable")
    return box


def _binding(box, session):
    # This performs the adapter's exact account/selection/configuration checks,
    # without obtaining or returning a bearer token or refreshing credentials.
    account, _, binding = box.service._account(session, identity=box.identity)
    credential = session.get(box.service.Credential, account.id)
    if (credential is None or credential.status != "ready" or not credential.sealed
            or credential.binding_digest != binding):
        raise LabError("account_connection_unavailable")
    return digest([account.id, binding, credential.connected_at.isoformat()])


def _current_binding(box):
    with box.service._session() as session:
        return _binding(box, session)


def _observation_id(app, role, key):
    return "account-read-" + digest([app.box, app.workspace, role, key])


def _stored_read(store, episode, identifier, role):
    try:
        return store.read(episode, identifier, role)
    except LabError as error:
        if str(error) == "artifact_not_found":
            return None
        raise


def _read_receipt(saved, *, replay):
    observation = saved["observation"]
    return {**BASE_RECEIPT, "status": "empty" if not observation["items"] else "ready",
        "read_key": saved["request"]["idempotency_key"],
        "observation_id": saved["id"], "observation_sha256": saved["sha256"],
        "source_sha256": digest(observation), "observation": observation,
        "workspace_id": saved["workspace_id"], "workspace_revision": saved["workspace_revision"],
        "saved_to_workspace": False, "idempotent_replay": replay,
        "limits": LIMITS[observation["kind"]],
        "next_action": "Select exact item IDs to save as workspace evidence, or leave the read unsaved."}


def _status(box):
    value = box.service.status(box.identity)
    return {**BASE_RECEIPT, "status": "ready" if value["state"] == "connected" else "unavailable",
        "provider": box.provider, "connection": value, "data_read": False,
        "next_action": "Read selected headers/calendar summaries." if value["state"] == "connected"
            else "A human must review the account connection; tools cannot sign in or add permission."}


def _read(app, store, episode, role, name, args):
    box = _box(app, args["provider"])
    identifier = _observation_id(app, role, args["idempotency_key"])
    saved = _stored_read(store, episode + ":accounts", identifier, role)
    binding = _current_binding(box)
    request = {"tool": name, **args}
    if saved is not None:
        if saved["request"] != request:
            raise LabError("account_read_idempotency_conflict")
        if (saved["requester_agent_id"] != app.agent_id(role)
                or saved["team_revision"] != app.team_revision):
            raise LabError("account_observation_role_changed")
        if saved["account_binding_sha256"] != binding:
            raise LabError("account_selection_changed")
        app.check_agent(role)
        return _read_receipt(saved, replay=True)

    value = box.read("mail" if name == "account_read_mail_headers" else "calendar")
    app.check_agent(role)
    if binding != _current_binding(box):
        raise LabError("account_selection_changed")
    with Session(app.engine) as session:
        snapshot = workspace.read(session, app.box, app.owner, app.workspace)
    saved = store.save(episode + ":accounts", identifier, {"request": request,
        "workspace_id": app.workspace, "box_id": app.box, "requester_role": role,
        "requester_agent_id": app.agent_id(role), "team_revision": app.team_revision,
        "workspace_revision": snapshot["revision"],
        "account_binding_sha256": binding,
        "observation": {"provider": box.provider, **value}, "share_with": [role]})
    return _read_receipt(saved, replay=False)


def _save(app, store, episode, role, args):
    saved = store.read(episode + ":accounts", args["observation_id"], role, args["observation_sha256"])
    if (saved.get("requester_role") != role or saved.get("requester_agent_id") != app.agent_id(role)
            or saved.get("workspace_id") != app.workspace or saved.get("box_id") != app.box
            or saved.get("team_revision") != app.team_revision):
        raise LabError("account_observation_scope_mismatch")
    observation = saved["observation"]
    selected_ids = args["item_ids"]
    by_id = {item["id"]: item for item in observation["items"]}
    if (len(set(selected_ids)) != len(selected_ids) or any(not isinstance(item, str)
            or not item or len(item) > 2048 or item not in by_id for item in selected_ids)):
        raise LabError("invalid_observation_selection")
    selected = [by_id[identifier] for identifier in sorted(selected_ids)]
    payload = {"schema": "synthetic_account_observation_evidence_v1",
        "source": "SYNTHETIC ONLY: parsed read-only account observations; no message bodies, patient match, clinical approval or external action.",
        "provider": observation["provider"], "kind": observation["kind"],
        "observed_at": observation["observed_at"], "more": observation["more"],
        "account": observation["account"], "items": selected,
        "source_observation_id": saved["id"], "source_observation_sha256": saved["sha256"],
        "source_sha256": digest(observation), "selection_sha256": digest(selected),
        "requester_role": role, "requester_agent_id": app.agent_id(role),
        "team_revision": app.team_revision,
        "selection_origin": "explicit agent tool request in synthetic human test driver",
        "limits": LIMITS[observation["kind"]]}
    content = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    content_sha = hashlib.sha256(content.encode()).hexdigest()
    # Namespace retry keys to this caller and episode, but never by selection:
    # changing selected items under the same key must conflict, not append.
    key = "account-selection-" + digest([episode, role, args["idempotency_key"]])
    box = _box(app, observation["provider"])
    with Session(app.engine) as session:
        _, bot, _ = provider_team.active_bot(session, app.box, app.owner,
            app.addresses[role], app.team_revision)
        if bot.agent_id != app.agent_id(role):
            raise LabError("agent_identity_changed")
        if _binding(box, session) != saved["account_binding_sha256"]:
            raise LabError("account_selection_changed")
        replay = session.scalar(select(WorkspaceEntry).where(
            WorkspaceEntry.workspace_id == app.workspace, WorkspaceEntry.idempotency_key == key))
        result = workspace.append(session, app.box, app.owner, app.workspace,
            expected=args["expected_workspace_revision"], key=key, kind="evidence", content=content,
            source_label=f"Synthetic {observation['provider']} {observation['kind']} observations — selected, unreviewed")
    return {**BASE_RECEIPT, "status": "saved", "saved_to_workspace": True,
        "workspace_id": app.workspace, "workspace_revision": result["entry_revision"],
        "entry_id": result["entry_id"], "entry_revision": result["entry_revision"],
        "content_sha256": content_sha, "source_sha256": digest(observation),
        "source_observation_id": saved["id"], "source_observation_sha256": saved["sha256"],
        "selected_item_ids": sorted(selected_ids), "selection_sha256": digest(selected),
        "idempotent_replay": replay is not None,
        "next_action": "Chief and permitted teammates can cite this exact saved workspace evidence for draft work; human review remains required."}


def _select(app, store, episode, role, args):
    identifier = _observation_id(app, role, args["read_key"])
    saved = store.read(episode + ":accounts", identifier, role)
    if saved.get("request", {}).get("idempotency_key") != args["read_key"]:
        raise LabError("account_read_key_mismatch")
    command = {"observation_id": identifier, "observation_sha256": saved["sha256"],
        **{key: value for key, value in args.items() if key != "read_key"}}
    return {**_save(app, store, episode, role, command), "read_key": args["read_key"]}


def execute(app, store, episode, role, name, args):
    """One typed dispatch seam for the role router; failures never disclose reads."""
    if name not in ACCOUNT_SCHEMAS:
        return {**BASE_RECEIPT, "status": "unavailable", "error": "unknown_account_tool"}
    if role not in ACCOUNT_TOOL_ROLES[name]:
        return {**BASE_RECEIPT, "status": "unavailable", "error": "account_tool_role_denied"}
    try:
        args = ACCOUNT_SCHEMAS[name][0].model_validate(args).model_dump()
    except ValidationError:
        return {**BASE_RECEIPT, "status": "failed", "error": "invalid_account_tool_arguments"}
    try:
        app.check_agent(role)
        if name == "account_save_selected_observations":
            result = _save(app, store, episode, role, args)
        elif name == "account_select_observed_items":
            result = _select(app, store, episode, role, args)
        elif name == "account_connection_status":
            result = _status(_box(app, args["provider"]))
            app.check_agent(role)
        else:
            # Serialize read/replay publication on this local store so identical
            # concurrent retries cannot produce a second provider observation.
            with store.lock:
                result = _read(app, store, episode, role, name, args)
    except (LabError, workspace.WorkspaceError) as error:
        # Application errors are fixed local codes; never return vendor bodies,
        # exception details, credentials or partial observations on failure.
        code = str(error) if isinstance(error, LabError) else error.code
        result = {**BASE_RECEIPT, "status": "failed", "error": code,
            "saved_to_workspace": False,
            "next_action": "Review current role/account/workspace state and explicitly retry the exact request when appropriate."}
    except Exception:
        result = {**BASE_RECEIPT, "status": "failed", "error": "account_read_or_save_failed",
            "saved_to_workspace": False,
            "next_action": "The read/save did not produce a usable result. Check account health and explicitly retry; no automatic retry occurred."}
    store.event(episode, role, "account_connector_tool", tool=name, status=result["status"],
        error=result.get("error"), entry_id=result.get("entry_id"),
        observation_id=result.get("observation_id"), idempotent_replay=result.get("idempotent_replay", False))
    return result
