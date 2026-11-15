"""Stub-PATH fence tests for T-PROD-3-SECRETS SSH session (synthetic only).

Uses real jq from the runner PATH. Never prints secret values.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
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


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _require_real_jq() -> str:
    jq = shutil.which("jq")
    assert jq, "real jq required on CI runner / agent PATH"
    # Must not be our stub — resolve and ensure it is the system tool.
    assert "bin/jq" not in jq or jq.startswith("/usr"), jq
    probe = subprocess.run(
        [jq, "-n", "1+1"], capture_output=True, text=True, check=False
    )
    assert probe.returncode == 0 and probe.stdout.strip() == "2"
    return jq


def _stub_bin(
    tmp_path: Path,
    *,
    open_fail: bool = False,
    install_fail: bool = False,
    hide_jq_after_open: bool = False,
    jq_missing: bool = False,
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

    real_jq = _require_real_jq()
    if jq_missing:
        _write_executable(
            bin_dir / "jq",
            "#!/bin/bash\necho \"STOP: jq missing (stub)\" >&2\nexit 127\n",
        )
    else:
        # Real jq first on PATH (absolute symlink). Shadow /usr/bin/jq.
        os.symlink(real_jq, bin_dir / "jq")

    _write_executable(bin_dir / "curl", "#!/bin/bash\necho 203.0.113.10\n")
    _write_executable(bin_dir / "sha256sum", "#!/bin/bash\nexec /usr/bin/sha256sum \"$@\"\n")
    _write_executable(bin_dir / "install", "#!/bin/bash\nexec /usr/bin/install \"$@\"\n")

    install_fail_lit = "true" if install_fail else "false"
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
    # Put stub bin first but keep /usr/bin so real jq remains reachable if symlink removed.
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
    staging = tmp_path / "staging"
    staging.mkdir(mode=0o700)
    (staging / "CLERK_SECRET_KEY").write_bytes(CANARY.encode())
    script = tmp_path / "run-session.sh"
    if mode == "sigint":
        # Real session wrapper: INT during install still closes via session traps.
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
    if mode == "success":
        assert result.returncode == 0, out
        assert "PASS: secrets SSH session complete" in result.stdout
        ssh_log = (tmp_path / "state" / "ssh_argv.log").read_text()
        assert "StrictHostKeyChecking=yes" in ssh_log
        assert str(identity) in ssh_log
        assert ADMIN_USERNAME in ssh_log
        assert "temp SSH rule closed" in out or "TEMP-JOHN-SSH-SECRETS-INSTALL gone" in out
        assert "secrets_transport.py" in ssh_log
        assert not staging.exists()


def test_tool_missing_before_open_never_opens(tmp_path):
    bin_dir = _stub_bin(tmp_path, jq_missing=True)
    identity = _identity(tmp_path)
    staging = tmp_path / "staging"
    staging.mkdir(mode=0o700)
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
    staging = tmp_path / "staging"
    staging.mkdir(mode=0o700)
    (staging / "CLERK_SECRET_KEY").write_bytes(CANARY.encode())
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


def test_recovery_runs_for_real_and_staging_rules(tmp_path):
    bin_dir = _stub_bin(tmp_path)
    identity = _identity(tmp_path)
    staging = tmp_path / "staging"
    staging.mkdir(mode=0o700)
    (staging / "CLERK_SECRET_KEY").write_bytes(CANARY.encode())
    # Seed an open rule then recover.
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


@pytest.mark.parametrize("mode", ["unset", "empty", "partial"])
def test_recovery_local_staging_unset_empty_partial_stops(tmp_path, mode):
    bin_dir = _stub_bin(tmp_path)
    identity = _identity(tmp_path)
    staging = tmp_path / "staging"
    if mode == "partial":
        staging.mkdir(mode=0o700)
        # partial: path points at a file, not a directory
        staging.rmdir()
        staging.write_text("not-a-dir")
    script = tmp_path / f"recovery-{mode}.sh"
    staging_export = {
        "unset": "unset LOCAL_STAGING",
        "empty": 'export LOCAL_STAGING=""',
        "partial": f'export LOCAL_STAGING="{staging}"',
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
    assert result.returncode != 0
    assert "STOP:" in out
    assert "PASS: recovery" not in result.stdout
    # Rule still deleted first even when staging STOP follows.
    rules = json.loads((tmp_path / "state" / "rules.json").read_text())
    assert all(r.get("name") != "TEMP-JOHN-SSH-SECRETS-INSTALL" for r in rules)


def test_sourcing_fences_does_not_open_or_close(tmp_path):
    bin_dir = _stub_bin(tmp_path)
    identity = _identity(tmp_path)
    staging = tmp_path / "staging"
    staging.mkdir(mode=0o700)
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


def test_fence_release_root_uses_install_d_0700_not_mkdir_p():
    install = (FENCES / "fence-ssh-secrets-install.sh").read_text()
    assert "install -d -o root -g root -m 0700" in install
    assert "mkdir -p" not in install
    assert "/etc/cosmabot missing" in install
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
