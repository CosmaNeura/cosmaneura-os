import pytest

from cosmas_os.application.database_fingerprint import DatabaseFingerprintError
from cosmas_os.application.workspace_fingerprint import (
    _constraint_tokens,
    _index_definition,
    fingerprint_workspace_database,
)


def test_dump_restore_literal_array_casts_have_one_representation():
    before = "CHECK (mode::text = ANY (ARRAY['submit'::character varying, 'reconcile'::character varying]::text[]))"
    after = "CHECK (mode::text = ANY (ARRAY['submit'::character varying::text, 'reconcile'::character varying::text]))"
    assert _constraint_tokens(before) == _constraint_tokens(after)
    assert _constraint_tokens(before) != _constraint_tokens(after.replace("reconcile", "unapproved"))


INDEX_BEFORE = "CREATE UNIQUE INDEX pending ON public.work USING btree (workspace_id) WHERE ((kind::text = 'conversation'::text) AND (state::text = ANY ((ARRAY['reserved'::character varying, 'running'::character varying])::text[])))"
INDEX_AFTER = "CREATE UNIQUE INDEX pending ON public.work USING btree (workspace_id) WHERE ((kind::text = 'conversation'::text) AND (state::text = ANY (ARRAY[('reserved'::character varying)::text, ('running'::character varying)::text])))"


def test_index_dump_restore_parenthesized_literal_array_casts_match():
    assert _index_definition(INDEX_BEFORE) == _index_definition(INDEX_AFTER)
    assert _index_definition("CREATE INDEX ordinary ON public.work (workspace_id)") == "CREATE INDEX ordinary ON public.work (workspace_id)"


@pytest.mark.parametrize("changed", [
    INDEX_AFTER.replace("'running'", "'completed'"),
    INDEX_AFTER.replace("'reserved'", "'running'").replace("'running'::character varying)::text]", "'reserved'::character varying)::text]"),
    INDEX_AFTER.replace("character varying", "character varying(4)"),
    INDEX_AFTER.replace("character varying", "character"),
    INDEX_AFTER.replace("'reserved'::character varying", "state::character varying"),
    INDEX_AFTER.replace("::text]", "::citext]"),
    INDEX_AFTER.replace(" AND ", " OR "),
    INDEX_AFTER.replace("CREATE UNIQUE INDEX", "CREATE INDEX"),
    INDEX_AFTER.replace("(workspace_id)", "(owner_id)"),
    INDEX_AFTER.replace("'reserved'", "'ARRAY[''reserved''::character varying]::text[]'"),
])
def test_index_normalization_preserves_predicate_uniqueness_types_and_values(changed):
    assert _index_definition(INDEX_BEFORE) != _index_definition(changed)


@pytest.mark.parametrize("literal", [
    "'ARRAY[''reserved''::character varying]::text[]'",
    r"E'ARRAY[\'reserved\'::character varying]::text[]'",
    '"ARRAY[reserved::character varying]::text[]"',
])
def test_index_quoted_lookalikes_are_unchanged(literal):
    assert _index_definition(literal) == literal


@pytest.mark.parametrize(("first", "second"), [
    ("x::varchar(4)::text", "x::text"),
    ("'long value'::character varying(4)::text", "'long value'::text"),
    ("x > 1 AND y > 2", "x > 1 OR y > 2"),
    ("ARRAY[x::character varying]::text[]", "ARRAY[x::text]"),
    ("'ARRAY[''x''::character varying]::text[]'", "'ARRAY[''x''::text]'"),
    ('"ARRAY[x::character varying]::text[]"', '"ARRAY[x::text]"'),
    (r"E'ARRAY[\'x\'::character varying]::text[]'", r"E'ARRAY[\'x\'::text]'"),
    ("CHECK (value >= 1)", "CHECK (value > 1)"),
])
def test_normalization_does_not_hide_changed_logic_casts_or_literal_contents(first, second):
    assert _constraint_tokens(first) != _constraint_tokens(second)


@pytest.mark.parametrize(("url", "mode", "verify"), [
    ("postgresql+psycopg://invented:secret@remote.invalid/w1a_restore", "synth_os", False),
    ("postgresql+psycopg://invented:secret@127.0.0.1/cosmas_os", "synth_os", False),
    ("postgresql+psycopg://invented:secret@127.0.0.1/w1a_restore?unreviewed=yes", "synth_os", False),
    ("postgresql+psycopg://invented:secret@127.0.0.1/w1a_restore", "synth_os", True),
])
def test_local_rehearsal_requires_explicit_loopback_profile(url, mode, verify, monkeypatch):
    from cosmas_os.application import workspace_fingerprint as module
    monkeypatch.setattr(module, "_make_database_engine", lambda _: pytest.fail("must not connect"))
    with pytest.raises(DatabaseFingerprintError):
        fingerprint_workspace_database(url, cosmas_env=mode, data_mode="synthetic", require_verify_full=verify)
