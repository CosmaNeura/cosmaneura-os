"""Research card provenance requires the saved receipt, never a copied label."""

from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from tests.unit.test_research import saved_fixture

from cosmas_os.application import research


def case():
    store, run, receipt, entry = saved_fixture()
    rows = [(receipt, run, entry)]
    queries = []

    def execute(statement):
        queries.append(statement)
        return SimpleNamespace(all=lambda: rows)

    return SimpleNamespace(store=SimpleNamespace(get=store.get, execute=execute),
        run=run, receipt=receipt, entry=entry,
        rows=rows, queries=queries, box=run.box_id, owner=run.owner_id, wid=run.workspace_id)


def markers(f, entries=None):
    return research.saved_packet_markers(f.store, f.box, f.owner, f.wid,
        [f.entry] if entries is None else entries)


def test_exact_saved_receipt_supplies_only_bound_marker_metadata():
    f = case()
    before = deepcopy(vars(f.entry))
    assert markers(f) == {f.entry.id: {"contract": "research.saved_packet_marker.v1",
        "run_id": f.run.id, "entry_id": f.entry.id, "entry_revision": f.entry.revision}}
    assert vars(f.entry) == before and len(f.queries) == 1


def test_same_label_and_body_without_a_receipt_remains_ordinary_evidence():
    f = case()
    f.rows.clear()
    assert f.entry.source_label == "Research · public source excerpts" and f.entry.content
    assert markers(f) == {}
    assert f.entry.kind == "evidence" and f.entry.content


def test_no_evidence_performs_no_research_query():
    f = case()
    assert markers(f, []) == {} and f.queries == []
    f.entry.kind = "scratchpad"
    assert markers(f) == {} and f.queries == []


@pytest.mark.parametrize("object_name,field", [
    ("receipt", "box_id"), ("receipt", "workspace_id"), ("receipt", "entry_id"), ("receipt", "run_id"),
    ("run", "box_id"), ("run", "workspace_id"), ("run", "owner_id"),
    ("entry", "box_id"), ("entry", "workspace_id"), ("entry", "actor_id"),
])
def test_in_scope_sql_result_still_requires_exact_current_owner_and_entry_binding(object_name, field):
    f = case()
    setattr(getattr(f, object_name), field, str(uuid4()))
    content = f.entry.content
    assert markers(f) == {} and f.entry.content == content


@pytest.mark.parametrize("field,value", [("revision", 8), ("request_hash", "0" * 64),
    ("idempotency_key", "forged"), ("source_label", "Ordinary evidence"),
    ("content", "Copied or modified research-looking source")])
def test_existing_saved_integrity_rules_reject_changed_entry_without_masking_it(field, value):
    f = case()
    setattr(f.entry, field, value)
    content = f.entry.content
    assert markers(f) == {} and f.entry.content == content


@pytest.mark.parametrize("change", ["request", "source_hash", "run_hash", "run_state", "record_hash"])
def test_invalid_saved_receipt_or_lookup_proof_omits_marker(change):
    f = case()
    if change == "request":
        f.receipt.request["extra"] = True
    elif change == "source_hash":
        f.receipt.request["source_hashes"] = ["0" * 64]
        f.receipt.request_sha256 = research.research_digest(f.receipt.request)
    elif change == "run_hash":
        f.run.request_sha256 = "0" * 64
    elif change == "run_state":
        f.run.state, f.run.results = "running", []
    else:
        f.run.results[0]["sha256"] = "0" * 64
    assert markers(f) == {} and f.entry.content


def test_duplicate_receipt_rows_are_ambiguous_even_if_one_would_validate():
    f = case()
    duplicate = deepcopy(f.receipt)
    duplicate.id, duplicate.request_sha256 = str(uuid4()), "0" * 64
    f.rows.append((duplicate, f.run, f.entry))
    assert markers(f) == {}


@pytest.mark.parametrize("error", [ValueError("invalid saved proof"), TypeError("unknown shape"),
    KeyError("missing proof"), AttributeError("missing row"), research.ws.WorkspaceError("research_selection_too_large")])
def test_failed_integrity_check_is_only_a_missing_marker(monkeypatch, error):
    f = case()
    original = f.entry.content

    def failed(*_):
        raise error

    monkeypatch.setattr(research, "_saved", failed)
    assert markers(f) == {} and f.entry.content == original


def test_marker_is_bound_again_to_the_validated_saved_receipt(monkeypatch):
    f = case()
    saved = research._saved(f.store, f.receipt)
    monkeypatch.setattr(research, "_saved", lambda *_: {**saved, "entry_revision": saved["entry_revision"] + 1})
    assert markers(f) == {}
