#!/usr/bin/env python3
"""Explicit synthetic setup and loopback serving. Never invokes hosted entrypoints."""
from __future__ import annotations

import argparse
import os

import uvicorn
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from cosmas_os.adapters.extension_observation_store import initialize_observations
from cosmas_os.extension_local_profile import LocalExtensionProfile
from cosmas_os.models import BoxContext, ExternalIdentity, Principal


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--init", action="store_true", help="Initialize an empty, dedicated local proof database")
    args = parser.parse_args()
    env_file = os.environ.get("COSMABOT_EXTENSION_ENV_FILE")
    if env_file:
        from dotenv import load_dotenv
        load_dotenv(env_file, override=False)
    try:
        profile = LocalExtensionProfile.from_env()
        if args.init:
            subject = os.environ.get("COSMABOT_EXTENSION_CLERK_SUBJECT", "")
            if not subject.startswith("user_") or len(subject) > 255:
                raise ValueError("local_development_subject_required")
            engine = create_engine(profile.database_url, echo=False, hide_parameters=True)
            with engine.begin() as connection:
                if inspect(connection).get_table_names() or "extension_signin_proof" in inspect(connection).get_schema_names():
                    raise ValueError("local_extension_database_must_be_empty")
                for table in [BoxContext.__table__, Principal.__table__, ExternalIdentity.__table__]:
                    table.create(connection)
                initialize_observations(connection)
                with Session(bind=connection) as session:
                    box = BoxContext(id=profile.box_id, display_name="Invented Extension Practice")
                    session.add(box)
                    session.flush()
                    owner = Principal(box_id=box.id, principal_type="human", state="active",
                                      display_name="Invented Extension Tester", is_owner=True)
                    session.add(owner)
                    session.flush()
                    session.add(ExternalIdentity(box_id=box.id, principal_id=owner.id, provider="clerk",
                        issuer=profile.issuer, subject=subject, organization_id=profile.organization_id,
                        reviewed_by="Local proof operator", evidence_ref="local:extension-signin-proof"))
                    session.flush()
            print("Initialized dedicated synthetic extension database")
            return
        uvicorn.run("cosmas_os.api.extension_local:local_app", factory=True, host="127.0.0.1",
                    port=8766, access_log=False, log_level="critical")
    except Exception:
        raise SystemExit("Local extension setup refused; check the dedicated development configuration") from None


if __name__ == "__main__":
    main()
