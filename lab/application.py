"""Real CosmaBot services on an owned disposable PostgreSQL database.

The simulated human is a test driver, never an agent tool. It imports a saved
agent draft, reviews exact content, and exercises F-8 with a local-only receipt.
"""

import os
import secrets
import socket
import subprocess
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TypedDict
from uuid import uuid4

from lab.store import LabError


class Proposal(TypedDict):
    expected: int
    key: str
    note_id: str
    body: str
    due_date: date
    expected_outcome: str
    share: bool


class Approval(TypedDict):
    revision_id: str
    digest: str
    choice: str


class OwnedPostgres:
    def __init__(self, root: Path, binary: Path):
        self.root, self.binary = root, binary
        self.data = root / "postgres"
        self.password = secrets.token_hex(20)
        self.owner = "cosmabot_lab"
        self.database = "w1a_agent_lab"
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.url = f"postgresql+psycopg://{self.owner}:{self.password}@127.0.0.1:{self.port}/{self.database}"

    def command(self, name, *args):
        env = {"PATH": os.defpath, "LANG": "C", "LC_ALL": "C", "PGPASSWORD": self.password}
        with (self.root / "postgres-lifecycle.log").open("a") as log:
            subprocess.run([str(self.binary / name), *map(str, args)], env=env,
                           stdout=log, stderr=subprocess.STDOUT, timeout=30, check=True)

    def __enter__(self):
        password_file = self.root / "temporary-postgres-password"
        password_file.write_text(self.password)
        password_file.chmod(0o600)
        try:
            self.command("initdb", "-D", self.data, "--username", self.owner, "--auth-local=trust",
                         "--auth-host=scram-sha-256", "--pwfile", password_file, "--no-locale", "--encoding=UTF8")
            self.command("pg_ctl", "-D", self.data, "-l", self.root / "postgres.log", "-o",
                         f"-h 127.0.0.1 -p {self.port} -k '' -c statement_timeout=15000 -c lock_timeout=5000",
                         "-w", "-t", "15", "start")
            self.command("createdb", "-h", "127.0.0.1", "-p", self.port, "-U", self.owner, self.database)
            return self
        except BaseException:
            self.close()
            raise
        finally:
            password_file.unlink(missing_ok=True)

    def close(self):
        if (self.data / "postmaster.pid").exists():
            self.command("pg_ctl", "-D", self.data, "-m", "fast", "-w", "-t", "15", "stop")

    def __exit__(self, *_):
        self.close()


class Application:
    def __init__(self, engine, case, event):
        from sqlalchemy.orm import Session

        from cosmas_os.application import provider_team, services, workspace
        from cosmas_os.models import AppointmentObservation, PatientLink

        self.engine, self.case, self.event = engine, case, event
        self.workflow = {"status": "drafts_only", "external_effects": 0}
        with Session(engine) as session:
            seed = services.provision_box(services.Container(session), "Synthetic Agent Lab — " + case.title)
            self.box, self.owner = seed["box_id"], seed["owner_id"]
            link = PatientLink(box_id=self.box, source_pair_key="lab:" + str(uuid4()),
                               label="Synthetic " + case.key, state="confirmed",
                               confirmed_by_principal_id=self.owner, attested_at=datetime.now(UTC))
            session.add(link)
            session.flush()
            appointment = AppointmentObservation(box_id=self.box, patient_link_id=link.id,
                external_id="lab:" + str(uuid4()), source="synthetic", start_at=datetime.now(UTC),
                patient_label="Synthetic " + case.key)
            session.add(appointment)
            session.commit()
            snapshot = workspace.create(session, self.box, self.owner, appointment.id, "lab-create", initial_synthetic_source=False)
            self.workspace = snapshot["id"]
            inputs = case.inputs or (("Invented laboratory fixture — " + case.title, case.source),)
            for index, (label, content) in enumerate(inputs):
                snapshot = workspace.append(session, self.box, self.owner, self.workspace, expected=snapshot["revision"],
                    key=f"lab-fixture-source-{index}", kind="evidence", content=content, source_label=label)["workspace"]
            configuration = provider_team.default_configuration()
            research_address = str(uuid4())
            configuration["bots"].append({"role": "research", "instance_id": research_address,
                                            "name": "Research", "enabled": True})
            installed = provider_team.save(session, self.box, self.owner, expected=0, key="lab-team",
                                           configuration=configuration)
            self.agents = {item["role"]: item["agent_id"] for item in installed["members"]}
            self.addresses = {role: research_address if role == "research" else role for role in self.agents}
            self.team_revision = installed["revision"]
        event("simulated_provider", "application_seeded", workspace_id=self.workspace,
              box_id=self.box, roles=list(self.agents))

    def agent_id(self, role):
        if role not in self.agents:
            raise LabError("unknown_agent")
        return self.agents[role]

    def check_agent(self, role):
        from sqlalchemy.orm import Session

        from cosmas_os.application import provider_team

        try:
            with Session(self.engine) as session:
                _, bot, _ = provider_team.active_bot(session, self.box, self.owner, self.addresses[role], self.team_revision)
                if bot.agent_id != self.agent_id(role):
                    raise LabError("agent_identity_changed")
        except LabError:
            raise
        except Exception as error:
            raise LabError("agent_authority_unavailable") from error

    def sources(self, metadata_only=False):
        from sqlalchemy.orm import Session

        from cosmas_os.application import workspace

        with Session(self.engine) as session:
            snapshot = workspace.read(session, self.box, self.owner, self.workspace)
        return [{"id": entry["id"], "revision": entry["revision"], "label": entry["source_label"],
                 **({} if metadata_only else {"content": entry["content"]})}
                for entry in snapshot["entries"] if entry["kind"] == "evidence"]

    def status(self):
        return {"workspace_id": self.workspace, "workflow": self.workflow,
                "human_review": "simulated provider only; agents cannot approve", "synthetic": True}

    def exercise_follow_up(self, note_artifact, follow_artifact):
        from sqlalchemy import func, select
        from sqlalchemy.orm import Session

        from cosmas_os.application import follow_up, note_review, workspace
        from cosmas_os.models import Decision, FollowUpReceipt, Operation, Principal

        def snapshot(session):
            return workspace.read(session, self.box, self.owner, self.workspace)

        def human_event(kind, **detail):
            self.event("simulated_provider", kind, principal_id=self.owner, **detail)

        with Session(self.engine) as session:
            w = snapshot(session)
            w = note_review.save(session, self.box, self.owner, self.workspace, expected=w["revision"],
                key="lab-import-note", base_note_id=None, source_reply_id=None,
                content="Imported synthetic agent draft; attribution retained in lab artifact " + note_artifact["sha256"] + "\n" + note_artifact["body"])["workspace"]
            note = w["note"]["latest"]
            human_event("note_imported", artifact_sha256=note_artifact["sha256"], note_id=note["id"])
            w = note_review.review(session, self.box, self.owner, self.workspace, note["id"],
                expected=w["revision"], key="lab-review", content_hash=note["content_hash"],
                source_hash=note["source_fingerprint"])["workspace"]
            human_event("note_reviewed", content_hash=note["content_hash"])
            proposal = Proposal(expected=w["revision"], key="lab-proposal", note_id=note["id"],
                body=follow_artifact["body"], due_date=date(2026, 10, 2),
                expected_outcome="Synthetic person confirms the next visit", share=True)
            created = follow_up.propose(session, self.box, self.owner, self.workspace, **proposal)
            item = created["workspace"]["follow_ups"][0]
            # Lost create response: repeat the exact request, then compare the durable ID.
            replay = follow_up.propose(session, self.box, self.owner, self.workspace, **proposal)
            if replay["workspace"]["follow_ups"][0]["ticket_id"] != item["ticket_id"]:
                raise LabError("duplicate_proposal")
            command = Approval(revision_id=item["revision_id"], digest=item["payload_hash"], choice="approve")
            try:
                follow_up.decide(session, self.box, self.agent_id("follow_up"), self.workspace, item["ticket_id"], **command)
            except workspace.WorkspaceError:
                session.rollback()
                human_event("agent_approval_denied")
            else:
                raise LabError("agent_was_able_to_approve")
            # Commit approval intent, close this Session, then recover in a new one.
            follow_up.decide(session, self.box, self.owner, self.workspace, item["ticket_id"], **command, defer_delivery=True)
            human_event("exact_approval_saved", ticket_id=item["ticket_id"], payload_hash=item["payload_hash"])
        with Session(self.engine) as session:
            # Same approval recovers the pending local effect, including a duplicate caller.
            for _ in range(2):
                follow_up.decide(session, self.box, self.owner, self.workspace, item["ticket_id"], **command)
            for _ in range(2):
                final = follow_up.complete(session, self.box, self.owner, self.workspace, item["ticket_id"],
                    revision_id=item["revision_id"], digest=item["payload_hash"], key="lab-complete",
                    evidence="SIMULATED HUMAN ATTESTATION: synthetic patient confirmed in the test scenario.")
            counts = {name: session.scalar(select(func.count()).select_from(model).where(model.box_id == self.box))
                      for name, model in (("operations", Operation), ("decisions", Decision), ("receipts", FollowUpReceipt))}
            decisions = list(session.scalars(select(Decision).where(Decision.box_id == self.box)))
            if counts != {"operations": 1, "decisions": 1, "receipts": 2}:
                raise LabError("duplicate_or_missing_workflow_effect")
            for decision in decisions:
                actor = session.get(Principal, decision.actor_principal_id)
                if actor is None or actor.principal_type != "human":
                    raise LabError("nonhuman_approval")
            self.workflow = {"status": final["workspace"]["follow_ups"][0]["state"], **counts,
                             "ticket_id": item["ticket_id"], "note_id": note["id"], "external_effects": 0,
                             "approval_actor": "simulated_human", "session_restart_recovered": True,
                             "duplicate_requests_reused_operation": True, "agent_approval_denied": True}
            human_event("workflow_verified", **self.workflow)
        return self.workflow
