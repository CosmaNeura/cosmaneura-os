"""Stub-PATH fence tests for T-PROD-3-SECRETS SSH session (synthetic only).

Uses real jq from the runner PATH. Never prints secret values.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import tempfile
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
FENCES = REPO / "infra/beta/vm/host/fences"
MODULE = REPO / "infra/beta/vm/host/secrets_transport.py"
PIN = REPO / "infra/beta/vm/host/secrets_transport.sha256"
CANARY = "CANARY_SECRET_VALUE_9f3a2c7b1e8d4a06_NEVER_PRINT"
JOHN_CIDR = "203.0.113.10/32"
ADMIN_USERNAME = "reviewed-admin"
IDENTITY_NAME = "id_ed25519_synth"
PROD_ACCOUNT = (
    "/subscriptions/00000000-0000-4000-8000-000000000001"
    "/resourceGroups/rg-cosmabot-prod-eus2-01"
    "/providers/Microsoft.CognitiveServices/accounts/oai-cbot-prd-abc123"
)
CATALOG_HOST_NAMES = (
    "CLERK_SECRET_KEY",
    "CLERK_ACCOUNT_DELETION_SECRET",
    "DATABASE_PASSWORD",
    "POSTGRES_PASSWORD",
    "REDIS_PASSWORD",
    "HUMAN_DEPLOY_EVIDENCE_REF",
    "WORKSPACE_LLM_API_KEY",
)


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _require_real_jq() -> str:
    jq = shutil.which("jq")
    assert jq, "real jq required on CI runner / agent PATH"
    assert "bin/jq" not in jq or jq.startswith("/usr"), jq
    probe = subprocess.run(
        [jq, "-n", "1+1"], capture_output=True, text=True, check=False
    )
    assert probe.returncode == 0 and probe.stdout.strip() == "2"
    return jq


def _mk_staging() -> Path:
    path = Path(tempfile.mkdtemp(prefix="cosmabot-staging.", dir="/tmp"))
    os.chmod(path, 0o700)
    return path


def _fill_complete_staging(staging: Path, *, canary_name: str | None = "CLERK_SECRET_KEY") -> None:
    for name in CATALOG_HOST_NAMES:
        if name == canary_name:
            (staging / name).write_bytes(CANARY.encode())
        else:
            (staging / name).write_bytes(f"synthetic-{name}-fixture".encode())
    (staging / "WORKSPACE_LLM_API_KEY.source-account").write_text(PROD_ACCOUNT)


def _stub_bin(
    tmp_path: Path,
    *,
    open_fail: bool = False,
    install_fail: bool = False,
    hide_jq_after_open: bool = False,
    jq_missing: bool = False,
    probe_auth_fail: bool = False,
) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    (state / "rules.json").write_text(
        json.dumps(
            [
                {
                    "name": "https",
                    "destinationPortRange": "443",
                    "port": "443",
                    "access": "Allow",
                    "priority": 100,
                    "protocol": "Tcp",
                    "sourceAddressPrefix": "*",
                    "source": "*",
                },
                {
                    "name": "deny-all-other-ingress",
                    "destinationPortRange": "*",
                    "port": "*",
                    "access": "Deny",
                    "priority": 4000,
                    "protocol": "*",
                    "sourceAddressPrefix": "*",
                    "source": "*",
                },
            ]
        )
    )
    (state / "close_count").write_text("0")
    (state / "open_count").write_text("0")
    (state / "argv.log").write_text("")
    (state / "ssh_argv.log").write_text("")
    (state / "ssh_remote.log").write_text("")
    (state / "python_argv.log").write_text("")

    real_jq = _require_real_jq()
    if jq_missing:
        _write_executable(
            bin_dir / "jq",
            "#!/bin/bash\necho \"STOP: jq missing (stub)\" >&2\nexit 127\n",
        )
    else:
        os.symlink(real_jq, bin_dir / "jq")

    _write_executable(bin_dir / "curl", "#!/bin/bash\necho 203.0.113.10\n")
    _write_executable(bin_dir / "sha256sum", "#!/bin/bash\nexec /usr/bin/sha256sum \"$@\"\n")
    _write_executable(bin_dir / "install", "#!/bin/bash\nexec /usr/bin/install \"$@\"\n")
    real_python = shutil.which("python3") or "/usr/bin/python3"
    _write_executable(
        bin_dir / "python3",
        textwrap.dedent(
            f"""\
            #!/bin/bash
            STATE="{state}"
            echo "python3 $*" >>"$STATE/python_argv.log"
            echo "python3 $*" >>"$STATE/argv.log"
            exec {real_python} "$@"
            """
        ),
    )

    install_fail_lit = "true" if install_fail else "false"
    probe_auth_lit = "true" if probe_auth_fail else "false"
    az_helper = bin_dir / "_az_stub.py"
    az_helper.write_text(
        textwrap.dedent(
            f"""\
            import json, sys
            from pathlib import Path
            state = Path({str(state)!r})
            argv = " ".join(sys.argv[1:])
            (state / "argv.log").write_text((state / "argv.log").read_text() + f"az {{argv}}\\n")
            rules_path = state / "rules.json"
            if "nsg rule create" in argv:
                if {open_fail!r}:
                    print("STOP: stub open fail", file=sys.stderr)
                    raise SystemExit(1)
                rules = [r for r in json.loads(rules_path.read_text()) if r.get("name") != "TEMP-JOHN-SSH-SECRETS-INSTALL"]
                rules.insert(1, {{
                    "name": "TEMP-JOHN-SSH-SECRETS-INSTALL",
                    "destinationPortRange": "22",
                    "destinationPortRanges": ["22"],
                    "port": "22",
                    "access": "Allow",
                    "priority": 200,
                    "protocol": "Tcp",
                    "sourceAddressPrefix": {JOHN_CIDR!r},
                    "source": {JOHN_CIDR!r},
                }})
                rules_path.write_text(json.dumps(rules))
                state.joinpath("open_count").write_text(
                    str(int(state.joinpath("open_count").read_text() or "0") + 1)
                )
                if {hide_jq_after_open!r}:
                    jq = Path({str(bin_dir)!r}) / "jq"
                    jq.unlink(missing_ok=True)
                    jq.write_text("#!/bin/bash\\necho STOP: jq missing after open >&2\\nexit 127\\n")
                    jq.chmod(0o755)
                raise SystemExit(0)
            if "nsg rule delete" in argv:
                rules = [r for r in json.loads(rules_path.read_text()) if r.get("name") != "TEMP-JOHN-SSH-SECRETS-INSTALL"]
                rules_path.write_text(json.dumps(rules))
                state.joinpath("close_count").write_text(
                    str(int(state.joinpath("close_count").read_text() or "0") + 1)
                )
                raise SystemExit(0)
            if "nsg rule list" in argv:
                rules = json.loads(rules_path.read_text())
                out = []
                for r in rules:
                    out.append({{
                        "name": r.get("name"),
                        "port": r.get("port") or r.get("destinationPortRange"),
                        "destinationPortRanges": r.get("destinationPortRanges") or (
                            [r.get("destinationPortRange")] if r.get("destinationPortRange") else []
                        ),
                        "access": r.get("access"),
                        "priority": r.get("priority"),
                        "protocol": r.get("protocol", "Tcp"),
                        "source": r.get("source") or r.get("sourceAddressPrefix"),
                    }})
                print(json.dumps(out))
                raise SystemExit(0)
            if "run-command" in argv:
                print(json.dumps({{
                    "value": [{{
                        "message": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFakeHostKeyForSyntheticFenceTestsOnly root@synth\\n"
                    }}]
                }}))
                raise SystemExit(0)
            print(f"STOP: unexpected az {{argv}}", file=sys.stderr)
            raise SystemExit(1)
            """
        )
    )
    _write_executable(
        bin_dir / "az",
        f"#!/bin/bash\nexec python3 '{az_helper}' \"$@\"\n",
    )
    _write_executable(
        bin_dir / "ssh",
        textwrap.dedent(
            f"""\
            #!/bin/bash
            STATE="{state}"
            echo "ssh $*" >>"$STATE/ssh_argv.log"
            echo "ssh $*" >>"$STATE/argv.log"
            REMOTE="${{@: -1}}"
            printf '%s\\n' "$REMOTE" >>"$STATE/ssh_remote.log"
            if [[ "$*" != *"StrictHostKeyChecking=yes"* ]]; then
              echo "STOP: StrictHostKeyChecking=yes required" >&2
              exit 1
            fi
            if [[ "$*" != *"-i "* ]]; then
              echo "STOP: ssh -i identity required" >&2
              exit 1
            fi
            if [[ "$*" != *"{ADMIN_USERNAME}@"* ]]; then
              echo "STOP: reviewed admin_username required" >&2
              exit 1
            fi
            if [[ "$*" == *"ConnectTimeout=3"* ]]; then
              if [[ "{probe_auth_lit}" == "true" ]]; then
                echo "Permission denied (publickey)." >&2
                exit 255
              fi
              echo "ssh: connect to host 203.0.113.50 port 22: Connection refused" >&2
              exit 255
            fi
            if [[ "{install_fail_lit}" == "true" ]]; then
              echo "STOP: stub install ssh fail" >&2
              exit 1
            fi
            cat >/dev/null
            exit 0
            """
        ),
    )
    _write_executable(
        bin_dir / "scp",
        "#!/bin/bash\necho \"STOP: scp must not be used for secret values\" >&2\nexit 1\n",
    )
    return bin_dir


def _identity(tmp_path: Path) -> Path:
    path = tmp_path / IDENTITY_NAME
    path.write_text("SYNTHETIC_SSH_IDENTITY_PLACEHOLDER\n")
    path.chmod(0o600)
    return path


def _env(bin_dir: Path, tmp_path: Path, staging: Path, identity: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:/usr/bin:/bin"
    env["RG"] = "rg-cosmabot-prod-eus2-01"
    env["VM_PUBLIC_IP"] = "203.0.113.50"
    env["RELEASE_ID"] = "rel-fence-1"
    env["LOCAL_STAGING"] = str(staging)
    env["PROD_KV_NAME"] = "kv-cbot-prd-lab01"
    env["SECRETS_TRANSPORT_PY"] = str(MODULE)
    env["SECRETS_TRANSPORT_SHA256_PIN"] = str(PIN)
    env["ADMIN_USERNAME"] = ADMIN_USERNAME
    env["SSH_IDENTITY_PATH"] = str(identity)
    return env


def _source_all() -> str:
    return "\n".join(
        f'source "{FENCES / name}"'
        for name in (
            "fence-ssh-nsg-open.sh",
            "fence-ssh-secrets-install.sh",
            "fence-ssh-nsg-close-verify.sh",
            "fence-ssh-nsg-recovery.sh",
            "fence-ssh-secrets-session.sh",
        )
    )


@pytest.mark.parametrize("mode", ["success", "open_fail", "install_fail", "sigint"])
def test_fence_session_always_close_verify_and_never_leaks_canary(tmp_path, mode):
    bin_dir = _stub_bin(
        tmp_path,
        open_fail=(mode == "open_fail"),
        install_fail=(mode == "install_fail"),
    )
    identity = _identity(tmp_path)
    staging = _mk_staging()
    _fill_complete_staging(staging)
    script = tmp_path / "run-session.sh"
    if mode == "sigint":
        script.write_text(
            textwrap.dedent(
                f"""\
                #!/bin/bash
                set -u
                {_source_all()}
                cosmabot_ssh_secrets_install() {{
                  kill -INT $$
                  return 1
                }}
                cosmabot_ssh_secrets_session
                """
            )
        )
    else:
        script.write_text(
            textwrap.dedent(
                f"""\
                #!/bin/bash
                set -u
                {_source_all()}
                cosmabot_ssh_secrets_session
                """
            )
        )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    result = subprocess.run(
        ["/bin/bash", str(script)],
        capture_output=True,
        text=True,
        check=False,
        env=_env(bin_dir, tmp_path, staging, identity),
    )
    out = (result.stdout or "") + (result.stderr or "")
    assert CANARY not in out
    argv_log = (tmp_path / "state" / "argv.log").read_text()
    assert CANARY not in argv_log
    assert "scp " not in argv_log
    rules = json.loads((tmp_path / "state" / "rules.json").read_text())
    assert all(r.get("name") != "TEMP-JOHN-SSH-SECRETS-INSTALL" for r in rules)
    close_count = int((tmp_path / "state" / "close_count").read_text() or "0")
    assert close_count >= 1
    assert not staging.exists(), f"staging must be gone on mode={mode}"
    if mode == "success":
        assert result.returncode == 0, out
        assert "PASS: secrets SSH session complete" in result.stdout
        ssh_log = (tmp_path / "state" / "ssh_argv.log").read_text()
        remote = (tmp_path / "state" / "ssh_remote.log").read_text()
        assert "StrictHostKeyChecking=yes" in ssh_log
        assert str(identity) in ssh_log
        assert ADMIN_USERNAME in ssh_log
        assert "secrets_transport.py" in remote
        assert "install -d -o root -g root -m 0700" in remote
        assert "sha256sum" in remote
        assert "--install-from-stdin" in remote
        py_log = (tmp_path / "state" / "python_argv.log").read_text()
        assert "--check-ssh-closed" in py_log
        assert "--check-ssh-probe" in py_log
        # Real closed/probe gate: python classifiers ran; PASS is not a bare fence echo alone.
        assert "SSH connection refused or connect timeout" in result.stdout


def test_tool_missing_before_open_never_opens(tmp_path):
    bin_dir = _stub_bin(tmp_path, jq_missing=True)
    identity = _identity(tmp_path)
    staging = _mk_staging()
    script = tmp_path / "no-jq-before.sh"
    script.write_text(
        textwrap.dedent(
            f"""\
            #!/bin/bash
            set -u
            {_source_all()}
            cosmabot_ssh_nsg_open
            """
        )
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    result = subprocess.run(
        ["/bin/bash", str(script)],
        capture_output=True,
        text=True,
        check=False,
        env=_env(bin_dir, tmp_path, staging, identity),
    )
    assert result.returncode != 0
    assert "preflight before open" in (result.stdout + result.stderr) or "needs working jq" in (
        result.stdout + result.stderr
    )
    assert int((tmp_path / "state" / "open_count").read_text() or "0") == 0
    assert int((tmp_path / "state" / "close_count").read_text() or "0") == 0


def test_tool_missing_after_open_still_deletes_rule(tmp_path):
    bin_dir = _stub_bin(tmp_path, hide_jq_after_open=True)
    identity = _identity(tmp_path)
    staging = _mk_staging()
    _fill_complete_staging(staging)
    script = tmp_path / "jq-gone-after.sh"
    script.write_text(
        textwrap.dedent(
            f"""\
            #!/bin/bash
            set -u
            {_source_all()}
            cosmabot_ssh_nsg_open || exit 1
            cosmabot_ssh_nsg_close_and_verify
            exit $?
            """
        )
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    result = subprocess.run(
        ["/bin/bash", str(script)],
        capture_output=True,
        text=True,
        check=False,
        env=_env(bin_dir, tmp_path, staging, identity),
    )
    rules = json.loads((tmp_path / "state" / "rules.json").read_text())
    assert all(r.get("name") != "TEMP-JOHN-SSH-SECRETS-INSTALL" for r in rules)
    assert int((tmp_path / "state" / "close_count").read_text() or "0") >= 1
    assert result.returncode != 0
    assert "needs jq after delete" in (result.stdout + result.stderr)


def test_recovery_runs_for_real_and_removes_staging(tmp_path):
    bin_dir = _stub_bin(tmp_path)
    identity = _identity(tmp_path)
    staging = _mk_staging()
    _fill_complete_staging(staging)
    script = tmp_path / "recovery.sh"
    script.write_text(
        textwrap.dedent(
            f"""\
            #!/bin/bash
            set -u
            {_source_all()}
            cosmabot_ssh_nsg_open || exit 1
            cosmabot_ssh_nsg_recovery_if_stranded
            """
        )
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    result = subprocess.run(
        ["/bin/bash", str(script)],
        capture_output=True,
        text=True,
        check=False,
        env=_env(bin_dir, tmp_path, staging, identity),
    )
    out = result.stdout + result.stderr
    assert CANARY not in out
    assert result.returncode == 0, out
    assert "PASS: recovery deleted" in result.stdout
    assert not staging.exists()
    rules = json.loads((tmp_path / "state" / "rules.json").read_text())
    assert all(r.get("name") != "TEMP-JOHN-SSH-SECRETS-INSTALL" for r in rules)


@pytest.mark.parametrize("mode", ["unset", "empty", "gone"])
def test_recovery_missing_staging_is_note_still_verifies_nsg(tmp_path, mode):
    """Missing staging is a NOTE; recovery still deletes then verifies NSG and may PASS."""
    bin_dir = _stub_bin(tmp_path)
    identity = _identity(tmp_path)
    staging = _mk_staging()
    _fill_complete_staging(staging)
    if mode == "gone":
        shutil.rmtree(staging)
    script = tmp_path / f"recovery-{mode}.sh"
    staging_export = {
        "unset": "unset LOCAL_STAGING",
        "empty": 'export LOCAL_STAGING=""',
        "gone": f'export LOCAL_STAGING="{staging}"',
    }[mode]
    script.write_text(
        textwrap.dedent(
            f"""\
            #!/bin/bash
            set -u
            {_source_all()}
            cosmabot_ssh_nsg_open || exit 1
            {staging_export}
            cosmabot_ssh_nsg_recovery_if_stranded
            """
        )
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    env = _env(bin_dir, tmp_path, staging if mode != "unset" else tmp_path / "unused", identity)
    if mode == "unset":
        env.pop("LOCAL_STAGING", None)
    result = subprocess.run(
        ["/bin/bash", str(script)], capture_output=True, text=True, check=False, env=env
    )
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    assert "PASS: recovery deleted" in result.stdout
    assert "NOTE:" in result.stdout
    assert "STOP:" not in out or "STOP: unexpected" not in out
    rules = json.loads((tmp_path / "state" / "rules.json").read_text())
    assert all(r.get("name") != "TEMP-JOHN-SSH-SECRETS-INSTALL" for r in rules)
    assert int((tmp_path / "state" / "close_count").read_text() or "0") >= 1


def test_empty_staging_stops_before_ssh_open_never_pass(tmp_path):
    bin_dir = _stub_bin(tmp_path)
    identity = _identity(tmp_path)
    staging = _mk_staging()
    script = tmp_path / "empty-stage.sh"
    script.write_text(
        textwrap.dedent(
            f"""\
            #!/bin/bash
            set -u
            {_source_all()}
            cosmabot_ssh_secrets_session
            """
        )
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    result = subprocess.run(
        ["/bin/bash", str(script)],
        capture_output=True,
        text=True,
        check=False,
        env=_env(bin_dir, tmp_path, staging, identity),
    )
    out = result.stdout + result.stderr
    assert result.returncode != 0
    assert "staging incomplete" in out or "STOP: staging" in out
    assert "PASS: secrets SSH session complete" not in result.stdout
    assert "PASS: staging complete" not in result.stdout
    assert int((tmp_path / "state" / "open_count").read_text() or "0") == 0
    assert int((tmp_path / "state" / "close_count").read_text() or "0") == 0
    assert staging.exists()


def test_partial_staging_stops_before_ssh_open_never_pass(tmp_path):
    bin_dir = _stub_bin(tmp_path)
    identity = _identity(tmp_path)
    staging = _mk_staging()
    (staging / "CLERK_SECRET_KEY").write_bytes(CANARY.encode())
    script = tmp_path / "partial-stage.sh"
    script.write_text(
        textwrap.dedent(
            f"""\
            #!/bin/bash
            set -u
            {_source_all()}
            cosmabot_ssh_secrets_session
            """
        )
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    result = subprocess.run(
        ["/bin/bash", str(script)],
        capture_output=True,
        text=True,
        check=False,
        env=_env(bin_dir, tmp_path, staging, identity),
    )
    out = result.stdout + result.stderr
    assert CANARY not in out
    assert result.returncode != 0
    assert "staging incomplete" in out or "STOP: staging" in out
    assert "PASS: secrets SSH session complete" not in result.stdout
    assert int((tmp_path / "state" / "open_count").read_text() or "0") == 0
    assert int((tmp_path / "state" / "close_count").read_text() or "0") == 0


def test_close_probe_auth_failure_fails_real_check_not_pass_echo(tmp_path):
    """Probe auth failure must FAIL via --check-ssh-probe, not a fence PASS echo."""
    bin_dir = _stub_bin(tmp_path, probe_auth_fail=True)
    identity = _identity(tmp_path)
    staging = _mk_staging()
    _fill_complete_staging(staging)
    script = tmp_path / "auth-fail-close.sh"
    script.write_text(
        textwrap.dedent(
            f"""\
            #!/bin/bash
            set -u
            {_source_all()}
            cosmabot_ssh_nsg_open || exit 1
            cosmabot_ssh_nsg_close_and_verify
            """
        )
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    result = subprocess.run(
        ["/bin/bash", str(script)],
        capture_output=True,
        text=True,
        check=False,
        env=_env(bin_dir, tmp_path, staging, identity),
    )
    out = result.stdout + result.stderr
    py_log = (tmp_path / "state" / "python_argv.log").read_text()
    assert "--check-ssh-closed" in py_log
    assert "--check-ssh-probe" in py_log
    assert result.returncode != 0
    assert "SSH still reachable" in out or "ssh_still_reachable" in out
    assert "PASS: TEMP-JOHN-SSH-SECRETS-INSTALL gone" not in result.stdout
    # Rule was still deleted first.
    rules = json.loads((tmp_path / "state" / "rules.json").read_text())
    assert all(r.get("name") != "TEMP-JOHN-SSH-SECRETS-INSTALL" for r in rules)


def test_guarded_rm_refuses_non_mktemp_path(tmp_path):
    bin_dir = _stub_bin(tmp_path)
    identity = _identity(tmp_path)
    bad = tmp_path / "not-mktemp-staging"
    bad.mkdir(mode=0o700)
    script = tmp_path / "bad-rm.sh"
    script.write_text(
        textwrap.dedent(
            f"""\
            #!/bin/bash
            set -u
            {_source_all()}
            export LOCAL_STAGING="{bad}"
            cosmabot_guarded_rm_local_staging
            """
        )
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    result = subprocess.run(
        ["/bin/bash", str(script)],
        capture_output=True,
        text=True,
        check=False,
        env=_env(bin_dir, tmp_path, bad, identity),
    )
    assert result.returncode != 0
    assert "STOP: guarded-rm" in (result.stdout + result.stderr)
    assert bad.exists()


def test_sourcing_fences_does_not_open_or_close(tmp_path):
    bin_dir = _stub_bin(tmp_path)
    identity = _identity(tmp_path)
    staging = _mk_staging()
    script = tmp_path / "source-only.sh"
    script.write_text(
        textwrap.dedent(
            f"""\
            #!/bin/bash
            {_source_all()}
            echo PASS: sourced-only
            """
        )
    )
    result = subprocess.run(
        ["/bin/bash", str(script)],
        capture_output=True,
        text=True,
        check=False,
        env=_env(bin_dir, tmp_path, staging, identity),
    )
    assert result.returncode == 0, result.stderr
    assert "PASS: sourced-only" in result.stdout
    assert int((tmp_path / "state" / "open_count").read_text() or "0") == 0
    assert int((tmp_path / "state" / "close_count").read_text() or "0") == 0


def test_fence_release_root_uses_install_d_0700_after_etc_cosmabot_precheck():
    install = (FENCES / "fence-ssh-secrets-install.sh").read_text()
    assert "install -d -o root -g root -m 0700" in install
    assert "test -d /etc/cosmabot" in install
    assert "/etc/cosmabot missing" in install
    assert "cosmabot_guarded_rm_local_staging" in install
    assert "mkdir -p" not in install
    assert "ADMIN_USERNAME" in install
    assert 'ssh -i "$SSH_IDENTITY_PATH"' in install
    assert "RELEASE_ID shape" in install


def test_session_uses_command_v_and_portable_traps():
    session = (FENCES / "fence-ssh-secrets-session.sh").read_text()
    assert "command -v cosmabot_ssh_nsg_open" in session
    assert "type -t" not in session
    assert "ZSH_VERSION" in session
    assert "cosmabot_ssh_session_save_traps" in session
    assert "trap -p" in session
    assert "|| true" not in session
    assert "--check-staging-complete" in session
