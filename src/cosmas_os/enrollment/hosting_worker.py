"""Separately enabled private allocation loop; never starts in the public API."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .allocation import WorkspaceAllocationWorker
from .config import EnrollmentSettings
from .hosting import HostingConfiguration, OpenTofuWorkspaceAllocator
from .migration import schema_ready
from .provisioning import ClerkProvisioningPort, EnrollmentProvisioner
from .service import EnrollmentService
from .stripe import StripeCommerce


def create_worker(path: Path, settings: EnrollmentSettings | None = None):
    selected = settings or EnrollmentSettings()
    config = HostingConfiguration.from_path(path)
    if (not config.value["enabled"] or not selected.workspace_allocation_enabled or not selected.provisioning_enabled
            or selected.registration_errors() or selected.billing_errors() or selected.data_mode != "synthetic"):
        raise ValueError("private staging allocation is not enabled and qualified")
    engine = create_engine(selected.database_url.get_secret_value(), pool_pre_ping=True, hide_parameters=True)
    if not schema_ready(engine):
        engine.dispose()
        raise ValueError("existing enrollment registry schema required")
    service = EnrollmentService(sessionmaker(engine, expire_on_commit=False), selected, StripeCommerce(selected))
    allocator = OpenTofuWorkspaceAllocator(service, config)
    provisioner = EnrollmentProvisioner(service, ClerkProvisioningPort(selected.clerk_secret_key.get_secret_value()))
    return WorkspaceAllocationWorker(service, provisioner, allocator), engine


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configuration", type=Path, required=True)
    parser.add_argument("--run", action="store_true", help="Explicitly execute the reviewed private hosting worker")
    parser.add_argument("--once", action="store_true")
    arguments = parser.parse_args()
    if not arguments.run:
        parser.error("execution is held unless --run is explicitly supplied on the private host")
    engine = None
    try:
        worker, engine = create_worker(arguments.configuration)
        while True:
            operation = worker.run_one()
            print(json.dumps({"allocation_operation": operation, "workspace_ready": False, "trial_started": False}), flush=True)
            if arguments.once:
                return 0
            time.sleep(15)
    except Exception as error:
        print(json.dumps({"error": "private_workspace_allocation_pending", "class": type(error).__name__}), flush=True)
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
