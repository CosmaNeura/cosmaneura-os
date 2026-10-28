"""Real saved Research receipts produce public display metadata, not model authority."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event, select
from tests.integration.test_workspace import encounter

from cosmas_os.adapters.public_research import record
from cosmas_os.api.research_schemas import Save, Search
from cosmas_os.application import provider_team as team
from cosmas_os.application import research
from cosmas_os.application import services as svc
from cosmas_os.application import workspace as ws
from cosmas_os.models import Principal, WorkspaceEntry
from cosmas_os.research_models import ResearchRun, ResearchSave


@pytest.fixture
def packet_case(session, seeded):
    box, owner = seeded["box_id"], seeded["owner_id"]
    appointment = encounter(session, box, owner)
    workspace = ws.create(session, box, owner, appointment.id, "invented-packet-workspace", initial_synthetic_source=False)
    bot = uuid4()
    configuration = team.default_configuration()
    configuration["bots"].append({"role": "research", "instance_id": str(bot), "name": "Research",
        "enabled": True, "include_notebook": False, "include_evidence": False})
    version = team.save(session, box, owner, expected=0, key="invented-packet-team", configuration=configuration)
    calls = []

    def lookup(source, query, *, check):
        check()
        calls.append((source, query))
        return [record(source, query, "a" * 64, identity="12345", title="Invented study",
            url="https://pubmed.ncbi.nlm.nih.gov/12345/", excerpt="Invented public research excerpt.")]

    observed = research.search(session, box, owner, workspace["id"],
        request=Search(contract_version=1, idempotency_key="invented-packet-lookup", expected_revision=workspace["revision"],
            team_revision=version["revision"], bot=bot, topic="literature", sources=["pubmed"],
            query="Invented public research", public_query_confirmed=True),
        configured={"pubmed"}, port=SimpleNamespace(lookup=lookup), check=lambda: 30, reauthenticate=lambda: None)
    saved = research.save(session, box, owner, workspace["id"], observed["run_id"],
        request=Save(contract_version=1, idempotency_key="invented-packet-save", expected_revision=workspace["revision"],
            source_hashes=[observed["results"][0]["sha256"]]), check=lambda: 30, reauthenticate=lambda: None)
    return SimpleNamespace(s=session, box=box, owner=owner, wid=workspace["id"], observed=observed,
        saved=saved, calls=calls)


def projected(f, *, revision=None):
    return ws.read(f.s, f.box, f.owner, f.wid, at_revision=revision)


def test_saved_receipt_and_identical_manual_copy_have_distinct_public_provenance(packet_case):
    f = packet_case
    entry = f.s.get(WorkspaceEntry, f.saved["entry_id"])
    assert entry is not None
    copied = ws.append(f.s, f.box, f.owner, f.wid, expected=f.saved["entry_revision"],
        key="invented-manual-copy", kind="evidence", source_label=entry.source_label, content=entry.content)
    public = projected(f)
    original, duplicate = public["entries"]
    assert original["research_packet"] == {"contract": "research.saved_packet_marker.v1",
        "run_id": f.saved["run_id"], "entry_id": f.saved["entry_id"], "entry_revision": f.saved["entry_revision"]}
    assert duplicate["id"] == copied["entry_id"] and "research_packet" not in duplicate
    assert original["content"] == duplicate["content"] == entry.content
    assert original["kind"] == duplicate["kind"] == "evidence"
    assert len(f.calls) == 1


def test_historical_projection_never_adds_a_later_packet(packet_case):
    f = packet_case
    assert projected(f, revision=f.saved["entry_revision"] - 1)["entries"] == []
    before = projected(f, revision=f.saved["entry_revision"])
    later = research.save(f.s, f.box, f.owner, f.wid, f.saved["run_id"],
        request=Save(contract_version=1, idempotency_key="invented-later-packet", expected_revision=f.saved["entry_revision"],
            source_hashes=[f.observed["results"][0]["sha256"]]), check=lambda: 30, reauthenticate=lambda: None)
    assert projected(f, revision=f.saved["entry_revision"])["entries"] == before["entries"]
    assert [entry["id"] for entry in projected(f)["entries"]] == [f.saved["entry_id"], later["entry_id"]]


def test_public_marker_never_changes_model_context_or_ordinary_source_content(packet_case, monkeypatch):
    f = packet_case
    public = projected(f)
    assert public["entries"][0]["research_packet"]

    def forbidden(*_):
        pytest.fail("Model-context projection must not query display provenance")

    monkeypatch.setattr(research, "saved_packet_markers", forbidden)
    model = ws._read_model_context(f.s, f.box, f.owner, f.wid)
    expected = [{key: value for key, value in entry.items() if key != "research_packet"} for entry in public["entries"]]
    assert model["entries"] == expected and len(f.calls) == 1


def test_owner_box_and_workspace_boundaries_remain_the_existing_authority(packet_case):
    f = packet_case
    other = Principal(box_id=f.box, principal_type="human", display_name="Other invented owner", state="active", is_owner=True)
    f.s.add(other)
    f.s.commit()
    foreign = svc.provision_box(svc.Container(f.s), "Other invented practice")
    for box, owner in ((f.box, other.id), (foreign["box_id"], foreign["owner_id"])):
        with pytest.raises(ws.WorkspaceError, match="workspace_unavailable"):
            ws.read(f.s, box, owner, f.wid)
    entry = f.s.get(WorkspaceEntry, f.saved["entry_id"])
    assert entry is not None
    assert research.saved_packet_markers(f.s, f.box, other.id, f.wid, [entry]) == {}
    assert research.saved_packet_markers(f.s, foreign["box_id"], f.owner, f.wid, [entry]) == {}
    assert research.saved_packet_markers(f.s, f.box, f.owner, str(uuid4()), [entry]) == {}


@pytest.mark.parametrize("change", ["receipt_hash", "run_owner", "entry_revision"])
def test_invalid_receipt_or_owner_proof_omits_marker_without_masking_evidence(packet_case, change):
    f = packet_case
    entry = f.s.get(WorkspaceEntry, f.saved["entry_id"])
    receipt = f.s.scalar(select(ResearchSave).where(ResearchSave.entry_id == f.saved["entry_id"]))
    run = f.s.get(ResearchRun, f.saved["run_id"])
    assert entry is not None and receipt is not None and run is not None
    original = entry.content
    # Deliberately corrupt only this session's cached proof, never immutable SQL history.
    with f.s.no_autoflush:
        if change == "receipt_hash":
            receipt.request_sha256 = "0" * 64
        elif change == "run_owner":
            run.owner_id = str(uuid4())
        else:
            entry.revision += 1
        public = projected(f)["entries"][0]
        assert "research_packet" not in public and public["kind"] == "evidence" and public["content"] == original
    f.s.expire_all()


def test_multiple_saved_packets_use_one_joined_proof_query(packet_case):
    f = packet_case
    later = research.save(f.s, f.box, f.owner, f.wid, f.saved["run_id"],
        request=Save(contract_version=1, idempotency_key="invented-second-packet", expected_revision=f.saved["entry_revision"],
            source_hashes=[f.observed["results"][0]["sha256"]]), check=lambda: 30, reauthenticate=lambda: None)
    entries = list(f.s.scalars(select(WorkspaceEntry).where(WorkspaceEntry.workspace_id == f.wid)))
    f.s.expunge_all()
    statements = []
    connection = f.s.connection()

    def counted(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(connection, "before_cursor_execute", counted)
    try:
        markers = research.saved_packet_markers(f.s, f.box, f.owner, f.wid, entries)
    finally:
        event.remove(connection, "before_cursor_execute", counted)
    assert set(markers) == {f.saved["entry_id"], later["entry_id"]}
    assert len(statements) == 1 and "research_saves" in statements[0] and "research_runs" in statements[0]
