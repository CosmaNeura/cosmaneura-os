"""Stub-PATH fence tests for T-PROD-3-SECRETS SSH session (synthetic only)."""
from __future__ import annotations

import json
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


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _stub_bin(tmp_path: Path, *, open_fail: bool = False, install_fail: bool = False) -> Path:
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

    jq_py = bin_dir / "_jq_impl.py"
    jq_py.write_text(
        textwrap.dedent(
            """\
            import json, sys
            argv = sys.argv[1:]
            data = sys.stdin.read()
            payload = json.loads(data) if data.strip() else None
            if argv and argv[0] == "-e":
                # Install-gate predicate: succeed when temp rule looks right.
                if isinstance(payload, list):
                    ok = any(
                        i.get("name") == "TEMP-JOHN-SSH-SECRETS-INSTALL"
                        and str(i.get("port") or i.get("destinationPortRange")) == "22"
                        and i.get("access") == "Allow"
                        and str(i.get("protocol", "")).lower() == "tcp"
                        and int(i.get("priority", -1)) == 200
                        for i in payload
                    )
                    raise SystemExit(0 if ok else 1)
                raise SystemExit(1)
            if argv and argv[0] == "-r":
                expr = " ".join(argv[1:])
                if "value[0].message" in expr or "ssh-ed25519" in expr:
                    print("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFakeHostKeyForSyntheticFenceTestsOnly")
                    raise SystemExit(0)
                if isinstance(payload, list) and "length" in expr:
                    if "TEMP-JOHN-SSH-SECRETS-INSTALL" in expr:
                        n = sum(1 for i in payload if i.get("name") == "TEMP-JOHN-SSH-SECRETS-INSTALL")
                        print(n)
                        raise SystemExit(0)
                    if "deny-all-other-ingress" in expr:
                        n = sum(
                            1
                            for i in payload
                            if i.get("name") == "deny-all-other-ingress"
                            and i.get("access") == "Deny"
                            and int(i.get("priority", -1)) == 4000
                        )
                        print(n)
                        raise SystemExit(0)
                    if 'port=="22"' in expr or ".port==22" in expr:
                        n = sum(
                            1
                            for i in payload
                            if str(i.get("port") or i.get("destinationPortRange")) == "22"
                            and i.get("access") == "Allow"
                        )
                        print(n)
                        raise SystemExit(0)
                    print(0)
                    raise SystemExit(0)
                if isinstance(payload, list) and 'name=\\(' in expr or (
                    isinstance(payload, list) and ".[] |" in expr and "length" not in expr
                ):
                    for item in payload:
                        port = item.get("port") or item.get("destinationPortRange")
                        print(
                            f"name={item.get('name')} port={port} "
                            f"access={item.get('access')} priority={item.get('priority')}"
                        )
                    raise SystemExit(0)
                print(0)
                raise SystemExit(0)
            print(json.dumps(payload))
            """
        )
    )
    _write_executable(
        bin_dir / "jq",
        f"#!/bin/bash\nexec python3 '{jq_py}' \"$@\"\n",
    )
    _write_executable(bin_dir / "curl", "#!/bin/bash\necho 203.0.113.10\n")
    _write_executable(bin_dir / "sha256sum", "#!/bin/bash\nexec /usr/bin/sha256sum \"$@\"\n")

    open_fail_lit = "true" if open_fail else "false"
    install_fail_lit = "true" if install_fail else "false"
    _write_executable(
        bin_dir / "az",
        textwrap.dedent(
            f"""\
            #!/bin/bash
            STATE="{state}"
            echo "az $*" >>"$STATE/argv.log"
            if [[ "$*" == *"nsg rule create"* ]]; then
              if [[ "{open_fail_lit}" == "true" ]]; then
                echo "STOP: stub open fail" >&2
                exit 1
              fi
              python3 - <<PY
            import json
            from pathlib import Path
            path = Path("$STATE/rules.json")
            rules = [r for r in json.loads(path.read_text()) if r.get("name") != "TEMP-JOHN-SSH-SECRETS-INSTALL"]
            rules.insert(1, {{
                "name": "TEMP-JOHN-SSH-SECRETS-INSTALL",
                "destinationPortRange": "22",
                "port": "22",
                "access": "Allow",
                "priority": 200,
                "protocol": "Tcp",
                "sourceAddressPrefix": "{JOHN_CIDR}",
                "source": "{JOHN_CIDR}",
            }})
            path.write_text(json.dumps(rules))
            Path("$STATE/open_count").write_text(str(int(Path("$STATE/open_count").read_text() or "0") + 1))
            PY
              exit 0
            fi
            if [[ "$*" == *"nsg rule delete"* ]]; then
              python3 - <<PY
            import json
            from pathlib import Path
            path = Path("$STATE/rules.json")
            rules = [r for r in json.loads(path.read_text()) if r.get("name") != "TEMP-JOHN-SSH-SECRETS-INSTALL"]
            path.write_text(json.dumps(rules))
            Path("$STATE/close_count").write_text(str(int(Path("$STATE/close_count").read_text() or "0") + 1))
            PY
              exit 0
            fi
            if [[ "$*" == *"nsg rule list"* ]]; then
              python3 - <<PY
            import json
            from pathlib import Path
            rules = json.loads(Path("$STATE/rules.json").read_text())
            out = []
            for r in rules:
                out.append({{
                    "name": r.get("name"),
                    "port": r.get("port") or r.get("destinationPortRange"),
                    "access": r.get("access"),
                    "priority": r.get("priority"),
                    "protocol": r.get("protocol", "Tcp"),
                    "source": r.get("source") or r.get("sourceAddressPrefix"),
                }})
            print(json.dumps(out))
            PY
              exit 0
            fi
            if [[ "$*" == *"run-command"* ]]; then
              python3 - <<'PY'
            import json
            print(json.dumps({{
              "value": [{{
                "message": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFakeHostKeyForSyntheticFenceTestsOnly root@synth\\n"
              }}]
            }}))
            PY
              exit 0
            fi
            echo "STOP: unexpected az $*" >&2
            exit 1
            """
        ),
    )
    _write_executable(
        bin_dir / "ssh",
        textwrap.dedent(
            f"""\
            #!/bin/bash
            STATE="{state}"
            echo "ssh $*" >>"$STATE/argv.log"
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


def _run_session(tmp_path: Path, bin_dir: Path, *, sigint: bool = False) -> subprocess.CompletedProcess:
    staging = tmp_path / "staging"
    staging.mkdir(mode=0o700)
    (staging / "CLERK_SECRET_KEY").write_bytes(CANARY.encode())
    script = tmp_path / "run-session.sh"
    script.write_text(
        textwrap.dedent(
            f"""\
            #!/bin/bash
            set -u
            export PATH="{bin_dir}:$PATH"
            export RG=rg-cosmabot-prod-eus2-01
            export VM_PUBLIC_IP=203.0.113.50
            export RELEASE_ID=rel-fence-1
            export LOCAL_STAGING="{staging}"
            export PROD_KV_NAME=kv-cbot-prd-lab01
            export SECRETS_TRANSPORT_PY="{MODULE}"
            export SECRETS_TRANSPORT_SHA256_PIN="{PIN}"
            source "{FENCES / 'fence-ssh-nsg-open.sh'}"
            source "{FENCES / 'fence-ssh-secrets-install.sh'}"
            source "{FENCES / 'fence-ssh-nsg-close-verify.sh'}"
            source "{FENCES / 'fence-ssh-secrets-session.sh'}"
            if [[ "{str(sigint).lower()}" == "true" ]]; then
              (
                sleep 0.05
                cosmabot_ssh_nsg_open
                kill -INT $$
              )
            else
              cosmabot_ssh_secrets_session
            fi
            """
        )
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    import os

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:/usr/bin:/bin:{env.get('PATH', '')}"
    return subprocess.run(
        ["/bin/bash", str(script)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


@pytest.mark.parametrize("mode", ["success", "open_fail", "install_fail", "sigint"])
def test_fence_session_always_close_verify_and_never_leaks_canary(tmp_path, mode):
    bin_dir = _stub_bin(
        tmp_path,
        open_fail=(mode == "open_fail"),
        install_fail=(mode == "install_fail"),
    )
    if mode == "sigint":
        # Explicit open then interrupted path still forces close via recovery-like call.
        script = tmp_path / "sigint.sh"
        script.write_text(
            textwrap.dedent(
                f"""\
                #!/bin/bash
                set -u
                export PATH="{bin_dir}:$PATH"
                export RG=rg-cosmabot-prod-eus2-01
                export VM_PUBLIC_IP=203.0.113.50
                export RELEASE_ID=rel-fence-1
                export LOCAL_STAGING="{tmp_path / 'staging'}"
                export PROD_KV_NAME=kv-cbot-prd-lab01
                export SECRETS_TRANSPORT_PY="{MODULE}"
                export SECRETS_TRANSPORT_SHA256_PIN="{PIN}"
                mkdir -p -m 700 "$LOCAL_STAGING"
                printf '%s' '{CANARY}' >"$LOCAL_STAGING/CLERK_SECRET_KEY"
                source "{FENCES / 'fence-ssh-nsg-open.sh'}"
                source "{FENCES / 'fence-ssh-secrets-install.sh'}"
                source "{FENCES / 'fence-ssh-nsg-close-verify.sh'}"
                source "{FENCES / 'fence-ssh-secrets-session.sh'}"
                trap 'cosmabot_ssh_nsg_close_and_verify || true' INT
                cosmabot_ssh_nsg_open || exit 1
                kill -INT $$
                """
            )
        )
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        result = subprocess.run(
            ["/bin/bash", str(script)], capture_output=True, text=True, check=False
        )
    else:
        result = _run_session(tmp_path, bin_dir, sigint=False)

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


def test_sourcing_fences_does_not_open_or_close(tmp_path):
    bin_dir = _stub_bin(tmp_path)
    script = tmp_path / "source-only.sh"
    script.write_text(
        textwrap.dedent(
            f"""\
            #!/bin/bash
            export PATH="{bin_dir}:$PATH"
            export RG=rg-cosmabot-prod-eus2-01
            export SECRETS_TRANSPORT_PY="{MODULE}"
            source "{FENCES / 'fence-ssh-nsg-open.sh'}"
            source "{FENCES / 'fence-ssh-secrets-install.sh'}"
            source "{FENCES / 'fence-ssh-nsg-close-verify.sh'}"
            source "{FENCES / 'fence-ssh-nsg-recovery.sh'}"
            source "{FENCES / 'fence-ssh-secrets-session.sh'}"
            echo PASS: sourced-only
            """
        )
    )
    result = subprocess.run(
        ["/bin/bash", str(script)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert "PASS: sourced-only" in result.stdout
    assert int((tmp_path / "state" / "open_count").read_text() or "0") == 0
    assert int((tmp_path / "state" / "close_count").read_text() or "0") == 0
