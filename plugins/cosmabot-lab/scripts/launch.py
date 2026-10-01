"""Generated local MCP configuration entry point; replay only, no installations."""

import argparse
import os
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--postgres-bin", type=Path, required=True)
    parser.add_argument("--temp-parent", type=Path, required=True)
    parser.add_argument("--case", default="walk_in")
    parser.add_argument("--role", default="chief")
    parser.add_argument("--mode", choices=("replay",), default="replay")
    parser.add_argument("--fault", choices=("none", "read_timeout", "lost_save_reply"), default="none")
    parser.add_argument("--connector-tools", action="store_true")
    args = parser.parse_args()
    repo = args.repo.expanduser().resolve()
    sys.path[:0] = [str(repo), str(repo / "src")]
    try:
        from lab.cases import CASES, ROLES
        from lab.mcp_doctor import (
            local_environment,
            output_parent_path,
            postgres_path,
            repository_path,
        )

        repo = repository_path(repo)
        pg = postgres_path(args.postgres_bin)
        parent = output_parent_path(args.temp_parent, repo)
        if args.case not in CASES or args.role not in ROLES:
            raise ValueError("unsupported_synthetic_startup")
        os.chdir(repo)
        os.execve(sys.executable, [sys.executable, "-B", "-m", "lab.mcp_server",
                                  "--postgres-bin", str(pg), "--case", args.case,
                                  "--role", args.role, "--mode", "replay", "--fault", args.fault,
                                  *(["--connector-tools"] if args.connector_tools else [])],
                  local_environment(repo, parent))
    except (ValueError, OSError):
        print("CosmaBot lab launch prerequisites changed; run python -m lab.mcp_doctor.", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
