import json
import os
import runpy
import subprocess
import sys
from pathlib import Path

import pytest
from lab import mcp_config, mcp_doctor

REPO = Path(__file__).resolve().parents[2]


def probe_runner(monkeypatch, *, version=(3, 13, 15), sdk="2.2.0", imports=True, pg=True):
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if "-c" in command:
            value = {"python": list(version), "mcp_version": sdk, "imports": {
                name: imports for name in ("lab.engine", "lab.application", "cosmas_os.model_registry")}}
            return subprocess.CompletedProcess(command, 0, json.dumps(value), "")
        if not pg:
            raise subprocess.TimeoutExpired(command, 5, output="secret must not be reported")
        return subprocess.CompletedProcess(command, 0, "program (PostgreSQL) 16.15\n", "")

    monkeypatch.setattr(mcp_doctor.subprocess, "run", run)
    return calls


def test_doctor_only_checks_prerequisites_without_inheriting_secrets(monkeypatch, tmp_path):
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "invented-secret-do-not-print")
    monkeypatch.setenv("DATABASE_URL", "postgresql://invented-private-location")
    calls = probe_runner(monkeypatch)
    before = list(tmp_path.iterdir())
    result = mcp_doctor.doctor(repo=REPO, python=Path(sys.executable),
                               postgres_bin=tmp_path, output_parent=tmp_path)
    assert result["ready"]
    assert not result["database_started"] and not result["provider_login"]
    assert list(tmp_path.iterdir()) == before
    assert len(calls) == 5
    assert all("AZURE_CLIENT_SECRET" not in kwargs["env"] and "DATABASE_URL" not in kwargs["env"]
               for _, kwargs in calls)
    assert calls[0][1]["env"]["PYTHONNOUSERSITE"] == "1"
    assert "invented-secret" not in json.dumps(result)
    assert all(command[-1] == "--version" for command, _ in calls[1:])


@pytest.mark.parametrize("kind", ["file", "symlink", "dangling_symlink"])
def test_doctor_refuses_checkout_env_before_any_project_import(monkeypatch, tmp_path, kind):
    repo = tmp_path / "repo"
    repo.mkdir()
    env_path = repo / ".env"
    if kind == "file":
        env_path.write_text("INVENTED_SECRET=must-not-be-read-or-reported")
    else:
        target = tmp_path / "environment"
        if kind == "symlink":
            target.write_text("INVENTED_SECRET=must-not-be-read-or-reported")
        env_path.symlink_to(target)
    calls = probe_runner(monkeypatch)
    result = mcp_doctor.doctor(repo=repo, python=Path(sys.executable),
                               postgres_bin=tmp_path, output_parent=tmp_path)
    assert result["ready"] is False
    assert result["error"] == "checkout_env_refused"
    assert result["checks"] == [{"name": "checkout_env_absent", "ok": False,
        "detail": "The source checkout must contain no .env file or .env symlink."}]
    assert not calls
    assert "INVENTED_SECRET" not in json.dumps(result)
    assert not result["database_started"] and not result["provider_login"]


@pytest.mark.parametrize("fault,expected", [
    ({"version": (3, 14, 0)}, "python_3_13"),
    ({"sdk": None}, "optional_mcp_sdk"),
    ({"sdk": "1.0.0"}, "optional_mcp_sdk"),
    ({"imports": False}, "project_imports"),
    ({"pg": False}, "postgres_binaries"),
])
def test_doctor_refuses_missing_or_incompatible_prerequisites(monkeypatch, tmp_path, fault, expected):
    probe_runner(monkeypatch, **fault)
    result = mcp_doctor.doctor(repo=REPO, python=Path(sys.executable),
                               postgres_bin=tmp_path, output_parent=tmp_path)
    assert not result["ready"]
    assert next(row for row in result["checks"] if row["name"] == expected)["ok"] is False
    assert "secret must not" not in json.dumps(result)


def test_interpreter_path_preserves_virtual_environment_symlink(tmp_path):
    actual = tmp_path / "base-python"
    actual.write_text("#!/bin/sh\nexit 0\n")
    actual.chmod(0o700)
    selected = tmp_path / "venv-python"
    selected.symlink_to(actual)
    assert mcp_doctor.interpreter_path(selected) == selected
    assert mcp_doctor.interpreter_path(selected) != selected.resolve()


def test_output_parent_refuses_repository_and_symlink_into_it(tmp_path):
    link = tmp_path / "source-link"
    link.symlink_to(REPO, target_is_directory=True)
    for value in (REPO, REPO / "lab", link):
        with pytest.raises(ValueError, match="outside_repository"):
            mcp_doctor.output_parent_path(value, REPO)


def test_configuration_defaults_replay_with_fresh_output_and_fixed_role(tmp_path):
    value = mcp_config.configuration(python=Path("/venv/bin/python"), repo=REPO,
        postgres_bin=Path("/pg/bin"), output_parent=tmp_path,
        launcher=REPO / "plugins/cosmabot-lab/scripts/launch.py")
    server = value["mcpServers"]["cosmabot-lab"]
    assert server["command"] == "/venv/bin/python"
    assert server["args"][-8:] == ["--case", "walk_in", "--role", "chief",
                                    "--mode", "replay", "--fault", "none"]
    assert "--output" not in server["args"]
    assert "--allow-azure" not in server["args"]
    assert set(server) == {"command", "args"}


@pytest.mark.parametrize("change", [{"role": "human"}, {"role": "owner"},
                                    {"case": "real_patient"}, {"fault": "send"}])
def test_configuration_rejects_unrecognized_startup_authority(tmp_path, change):
    kwargs = dict(python=Path("/venv/bin/python"), repo=REPO, postgres_bin=Path("/pg/bin"),
                  output_parent=tmp_path, launcher=tmp_path / "launch.py")
    with pytest.raises(ValueError, match="unsupported_synthetic_startup"):
        mcp_config.configuration(**kwargs, **change)


def test_package_copy_is_explicit_and_does_not_change_source_or_existing_config(monkeypatch, tmp_path):
    monkeypatch.setattr(mcp_config, "doctor", lambda **_: {"ready": True})
    source = REPO / "plugins/cosmabot-lab/.mcp.json"
    original = source.read_bytes()
    destination = tmp_path / "cosmabot-lab"
    kwargs = dict(repo=REPO, python=Path(sys.executable), postgres_bin=tmp_path,
                  output_parent=tmp_path, destination=destination, package=True,
                  case="walk_in", role="chief", fault="none")
    result = mcp_config.generate(**kwargs)
    assert result["configured"] and not result["installed"] and not result["activated"]
    config = json.loads((destination / ".mcp.json").read_text())
    manifest = json.loads((destination / ".codex-plugin/plugin.json").read_text())
    assert manifest["description"].startswith("Configured")
    assert (destination / "README.md").read_text().startswith("This generated copy is configured")
    assert str(destination / "scripts/launch.py") in config["mcpServers"]["cosmabot-lab"]["args"]
    assert source.read_bytes() == original
    assert (destination / ".mcp.json").stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="destination_must_be_new"):
        mcp_config.generate(**kwargs)
    assert json.loads((destination / ".mcp.json").read_text()) == config


def test_no_package_is_written_when_doctor_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(mcp_config, "doctor", lambda **_: {"ready": False})
    with pytest.raises(ValueError, match="doctor_not_ready"):
        mcp_config.generate(repo=REPO, python=Path(sys.executable), postgres_bin=tmp_path,
            output_parent=tmp_path, destination=tmp_path / "cosmabot-lab", package=True,
            case="walk_in", role="chief", fault="none")
    assert not list(tmp_path.iterdir())


def test_configuration_never_overwrites_or_targets_personal_configuration(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    for name in (".codex", ".agents"):
        (tmp_path / name).mkdir()
        with pytest.raises(ValueError, match="global_configuration"):
            mcp_config.destination_path(tmp_path / name / "config.json")
    existing = tmp_path / "existing.json"
    existing.write_text("retain this exact config")
    with pytest.raises(FileExistsError):
        mcp_config.write_config(existing, {"mcpServers": {}})
    assert existing.read_text() == "retain this exact config"


def test_launcher_uses_real_module_and_minimal_environment_without_a_reused_episode(monkeypatch, tmp_path):
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "invented-secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql://wrong-database")
    monkeypatch.setattr(mcp_doctor, "postgres_path", lambda value: Path(value))
    command = []
    monkeypatch.setattr(os, "execve", lambda *args: command.append(args))
    monkeypatch.setattr(os, "chdir", lambda _: None)
    script = REPO / "plugins/cosmabot-lab/scripts/launch.py"
    monkeypatch.setattr(sys, "argv", [str(script), "--repo", str(REPO), "--postgres-bin", str(tmp_path),
                                     "--temp-parent", str(tmp_path)])
    before = sys.path[:]
    try:
        runpy.run_path(str(script), run_name="__main__")
    finally:
        sys.path[:] = before
    assert len(command) == 1
    executable, args, env = command[0]
    assert executable == sys.executable
    assert args[1:4] == ["-B", "-m", "lab.mcp_server"]
    assert "--output" not in args and args[args.index("--mode") + 1] == "replay"
    assert env["TMPDIR"] == str(tmp_path)
    assert env["PYTHONNOUSERSITE"] == "1"
    assert "DATABASE_URL" not in env and "AZURE_CLIENT_SECRET" not in env


def test_launcher_rejects_azure_before_dispatch(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["launch.py", "--repo", str(REPO), "--postgres-bin", "/pg",
                                     "--temp-parent", "/tmp", "--mode", "azure"])
    with pytest.raises(SystemExit) as error:
        runpy.run_path(str(REPO / "plugins/cosmabot-lab/scripts/launch.py"), run_name="__main__")
    assert error.value.code == 2
    assert "invalid choice" in capsys.readouterr().err
