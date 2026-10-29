"""Pure bounded manifest validation; all people and identifiers are invented."""

import json
import os
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from cosmas_os.application.standalone_practice import StandalonePracticeManifest


def manifest_input():
    return json.loads((Path(__file__).parents[1] / "fixtures/standalone-practice-manifest.json").read_text())


def test_explicit_invented_manifest_is_closed_and_canonical():
    value = StandalonePracticeManifest.model_validate(manifest_input())
    assert value.provenance == "fresh_invented_cosmabot_practice"
    offset = value.appointments[0].start_at.utcoffset()
    assert offset is not None and offset.total_seconds() == 0


@pytest.mark.parametrize("change", [
    lambda m: m.update(confirm_synthetic_only=1),
    lambda m: m.update(provenance="main_platform_clone"),
    lambda m: m.update(database_name="cosmas_os"),
    lambda m: m.update(instance_id="00000000-0000-0000-0000-000000000001"),
    lambda m: m.update(dataset_id=m["instance_id"]),
    lambda m: m["identity"].update(clinic_display_name="Cosmas MD"),
    lambda m: m["identity"].update(email="invented@example.invalid"),
    lambda m: m["patients"][0].update(label="Unlabelled person"),
    lambda m: m["patients"].append(m["patients"][0]),
    lambda m: m["appointments"][0].update(patient_id=m["dataset_id"]),
    lambda m: m["appointments"][0].update(start_at="2026-10-28T14:00:00"),
    lambda m: m["appointments"][0].update(core_tenant_ref="invented_forbidden_reference"),
    lambda m: m["patients"].extend([m["patients"][0]] * 12),
])
def test_rejects_ambiguous_or_unreviewed_manifest_inputs(change):
    value = manifest_input()
    change(value)
    with pytest.raises(ValidationError):
        StandalonePracticeManifest.model_validate(value)


@pytest.mark.parametrize("kind", ["unconfirmed", "bad_phase", "world_readable", "duplicate", "symlink", "oversize", "fifo"])
def test_host_cli_rejects_unsafe_manifest_before_opening_database(tmp_path, monkeypatch, kind):
    from cosmas_os import cli

    path = tmp_path / "reviewed.json"
    path.write_text(json.dumps(manifest_input()))
    path.chmod(0o600)
    args = ["bootstrap-standalone-synthetic-practice", str(path), "--phase",
            "wrong" if kind == "bad_phase" else "reserve"]
    if kind != "unconfirmed":
        args.append("--confirm-reviewed-synthetic-only")
    if kind == "world_readable":
        path.chmod(0o644)
    elif kind == "duplicate":
        path.write_text('{"schema_version":"one","schema_version":"two"}')
    elif kind == "symlink":
        link = tmp_path / "linked.json"
        link.symlink_to(path)
        args[1] = str(link)
    elif kind == "oversize":
        path.write_text(" " * 32769)
    elif kind == "fifo":
        path.unlink()
        os.mkfifo(path, 0o600)

    def forbidden():
        pytest.fail("unsafe manifest attempted database access")

    monkeypatch.setattr(cli, "_session", forbidden)
    result = CliRunner().invoke(cli.app, args)
    assert result.exit_code != 0
    assert "Error" in result.output


def test_host_cli_bounds_opened_file_read_and_rejects_growth(tmp_path, monkeypatch):
    from cosmas_os import cli

    path = tmp_path / "reviewed.json"
    path.write_text(json.dumps(manifest_input()))
    path.chmod(0o600)
    original = os.fdopen
    requested = []

    class GrowingFile:
        def __init__(self, descriptor, mode):
            self.file = original(descriptor, mode)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            self.file.close()

        def fileno(self):
            return self.file.fileno()

        def read(self, maximum):
            requested.append(maximum)
            value = self.file.read(maximum)
            with path.open("ab") as writer:
                writer.write(b" " * 32768)
            return value

    monkeypatch.setattr(cli.os, "fdopen", GrowingFile)
    monkeypatch.setattr(cli, "_session", lambda: pytest.fail("changed manifest opened database"))
    result = CliRunner().invoke(cli.app, ["bootstrap-standalone-synthetic-practice", str(path),
        "--phase", "reserve", "--confirm-reviewed-synthetic-only"])
    assert result.exit_code != 0 and "changed while it was read" in result.output
    assert requested == [32768]
