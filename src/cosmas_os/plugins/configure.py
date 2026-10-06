"""Create a runnable project-local package using an existing virtual environment."""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from cosmas_os.plugins.runtime import origin_checked


def generate(destination, *, python, source, origin, token_file=None, workspace_id=None):
    destination = Path(destination).absolute()
    source = Path(source).resolve(strict=True)
    python = Path(python).absolute()  # Keep the venv symlink; resolving changes sys.prefix.
    token_file = Path(token_file).absolute() if token_file is not None else None
    if (destination.exists() or destination.is_symlink() or not destination.parent.is_dir()
            or not python.is_file() or not os.access(python, os.X_OK)
            or not (source / "src/cosmas_os/plugins/server.py").is_file()):
        raise ValueError("new_destination_and_existing_environment_required")
    args = ["-B", "-c", "import sys; sys.path.insert(0, sys.argv.pop(1)); from cosmas_os.plugins.server import main; raise SystemExit(main())",
            str(source / "src"), "--origin", origin_checked(origin)]
    if token_file is not None:
        args.extend(["--token-file", str(token_file)])
    if workspace_id:
        from uuid import UUID
        if str(UUID(workspace_id)) != workspace_id or UUID(workspace_id).int == 0:
            raise ValueError("invalid_workspace")
        args.extend(["--workspace-id", workspace_id])
    shutil.copytree(source / "plugins/cosmabot-connectors", destination,
                    ignore=shutil.ignore_patterns(".mcp.json", "app-session.json"))
    if token_file is not None:
        config = destination / ".mcp.json"
        content = {"mcpServers": {"cosmabot-connectors": {"command": str(python), "args": args}}}
    else:
        # This profile is for a trusted authenticated application host. An
        # unbound stdio entry would falsely imply browser-session access.
        config = destination / "app-session.json"
        content = {"contract": "cosmas-plugin-app-session.v1", "origin": origin_checked(origin),
                   "workspace_id": workspace_id, "authentication": "current_app_session",
                   "requires_authenticated_host_adapter": True, "account_status": "not_checked"}
    config.write_text(json.dumps(content, indent=2) + "\n")
    config.chmod(0o600)
    return {"package": str(destination), "configured": True, "installed": False,
            "transport": "authenticated_product_http" if token_file else "current_app_session",
            "external_mcp_configured": token_file is not None, "credentials_stored": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--token-file", type=Path, help="Optional external-stdio compatibility; never read browser credentials")
    parser.add_argument("--workspace-id")
    args = parser.parse_args(argv)
    result = generate(args.output, python=args.python, source=args.source, origin=args.origin,
                      token_file=args.token_file, workspace_id=args.workspace_id)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
