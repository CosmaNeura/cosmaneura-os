"""A real selected header and observed slot retain exact handoff outcomes."""

from lab.administrative_journey import CASE, AdministrativeWorld, run_administrative
from tests.integration.test_virtual_clinic_lab import clinic as clinic


def test_administrative_replay_persists_human_handoff_and_unsubmitted_appointment(clinic):
    app, store = clinic
    result = run_administrative(app, store, "administrative-replay", None)
    assert result["passed"], result["failures"]
    assert all(result["checks"].values())
    assert result["application"]["external_effects"] == 0
    assert result["application"]["appointment"]["operation_id"] is None
    assert result["application"]["inbox"]["incomplete_message"] is True
    assert result["application"]["inbox"]["completed"] is False


def test_human_review_and_booking_are_never_administrative_agent_tools(clinic):
    app, store = clinic
    world = AdministrativeWorld(store, "administrative-role-boundary", CASE, app, prepare_fax=False)
    try:
        for role, required in world.role_model_tools.items():
            offered = {tool["function"]["name"] for tool in world.model_tools(role)}
            assert offered == world.common_model_tools | required
            assert not any(name.startswith("fax_") for name in offered)
            assert "delegate_team" not in offered
        for name in ("human_review_assign", "human_accept", "human_execute", "book_appointment"):
            assert world.execute("chief", name, {})["error"] == "unknown_tool"
        assert world.execute("scribe", "google_inbox_read_headers", {"idempotency_key": "read-one"})["error"] == "tool_not_available_for_role"
        assert world.execute("research", "scheduling_read_availability", {})["error"] == "tool_not_available_for_role"
    finally:
        world.close()


def test_wrong_uuid_reference_explains_exact_recovery_without_reading_or_saving(clinic):
    app, store = clinic
    world = AdministrativeWorld(store, "administrative-reference-recovery", CASE, app, prepare_fax=False)
    try:
        original = world.execute("scribe", "list_sources", {})[0]
        failed = world.execute("scribe", "read_selected_source", {"source_ref": original["id"]})
        assert failed["error"] == "invalid_tool_arguments"
        assert original["source_ref"] in failed["allowed_source_refs"]
        assert failed["already_read_source_refs"] == []
        assert not world.source_reads["scribe"]
        world.execute("scribe", "read_selected_source", {"source_ref": original["source_ref"]})
        arguments = {"body": "Synthetic draft; unknown diagnosis and optional DOB.",
            "source_refs": [original["id"]], "dependency_roles": []}
        failed = world.execute("scribe", "save_connector_draft", arguments)
        assert failed["error"] == "source_outside_selected_encounter"
        assert failed["already_read_source_refs"] == [original["source_ref"]]
        assert not store.visible(world.episode, "scribe")
        recovered = world.execute("scribe", "save_connector_draft",
            {**arguments, "source_refs": failed["already_read_source_refs"]})
        assert recovered["id"] == "scribe" and recovered["source_ids"] == [original["id"]]
    finally:
        world.close()
