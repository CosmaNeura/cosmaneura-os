#!/usr/bin/python3
"""Read-only full workspace comparison; run with the reviewed application's Python.

The production CLI requires verify-full TLS and the nonadmin cosmas login. It
never starts an application, changes roles, promotes recovery, or fetches cloud
credentials. A local harness may explicitly supply its synthetic SQLAlchemy
engine and disable TLS; the production CLI has no switch for that substitution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path

from cosmas_os.application.database_fingerprint import _make_database_engine, _validate_database_url
from cosmas_os.application.workspace_fingerprint import (
    _CATALOG_QUERIES,
    WORKSPACE_FINGERPRINT_CONTRACT,
    fingerprint_workspace_database,
)
from cosmas_os.model_registry import metadata
from cosmas_os.runtime_schema import EXPECTED_SCHEMA_REVISION
from sqlalchemy import text

CONTRACT = 'cosmabot-workspace-restore-proof-v1'


def require(condition: bool) -> None:
    if not condition:
        raise ValueError('workspace restore proof refused')


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def measure(database_url: str, *, restored: bool, require_verify_full: bool = True) -> dict:
    _validate_database_url(database_url, require_verify_full=require_verify_full)
    engine = _make_database_engine(database_url)
    try:
        with engine.connect().execution_options(isolation_level='REPEATABLE READ') as connection:
            with connection.begin():
                connection.execute(text('SET TRANSACTION READ ONLY'))
                role = connection.execute(text("""SELECT current_user AS username,
                    session_user AS session_username, rolsuper, rolcreatedb, rolcreaterole,
                    rolreplication, rolbypassrls,
                    current_setting('transaction_read_only') AS read_only,
                    EXISTS(SELECT 1 FROM pg_auth_members WHERE member=r.oid) AS memberships,
                    pg_is_in_recovery() AS recovery,
                    CASE WHEN pg_is_in_recovery() THEN pg_get_wal_replay_pause_state() END AS paused,
                    CASE WHEN pg_is_in_recovery() THEN pg_last_wal_replay_lsn()::text END AS replay_lsn,
                    current_setting('recovery_target_lsn', true) AS target_lsn
                    FROM pg_roles r WHERE rolname=current_user""")).mappings().one()
                state = dict(role)
                require(state['username'] == state['session_username'] == 'cosmas')
                require(all(state[key] is False for key in (
                    'rolsuper', 'rolcreatedb', 'rolcreaterole', 'rolreplication',
                    'rolbypassrls', 'memberships')))
                require(state['read_only'] == 'on' and state['recovery'] is restored)
                if restored:
                    require(state['paused'] == 'paused')
        fingerprint = fingerprint_workspace_database(
            database_url, cosmas_env='early_adopter_beta', data_mode='synthetic',
            database_engine=engine, require_verify_full=require_verify_full,
        )
        return {'contract': CONTRACT, 'status': 'measured', 'database_state': state,
                'fingerprint': json.loads(fingerprint.sanitized_json())}
    finally:
        engine.dispose()


def checked_snapshot(value: dict, *, restored: bool) -> dict:
    require(set(value) == {'contract', 'status', 'database_state', 'fingerprint'})
    require(value['contract'] == CONTRACT and value['status'] == 'measured')
    state = value['database_state']
    require(state['username'] == state['session_username'] == 'cosmas')
    require(state['read_only'] == 'on' and state['recovery'] is restored)
    require(all(state[key] is False for key in (
        'rolsuper', 'rolcreatedb', 'rolcreaterole', 'rolreplication',
        'rolbypassrls', 'memberships')))
    if restored:
        require(state['paused'] == 'paused')
    fingerprint = value['fingerprint']
    require(set(fingerprint) == {'contract', 'status', 'schema_revision', 'tables',
                                 'catalog', 'aggregate_sha256', 'evidence_sha256'})
    require(set(fingerprint['catalog']) == set(_CATALOG_QUERIES))
    aggregate = {key: fingerprint[key] for key in ('schema_revision', 'tables', 'catalog')}
    require(hashlib.sha256(canonical(aggregate)).hexdigest() == fingerprint['aggregate_sha256'])
    require(fingerprint['contract'] == WORKSPACE_FINGERPRINT_CONTRACT
            and fingerprint['status'] == 'snapshot_ready'
            and fingerprint['schema_revision'] == EXPECTED_SCHEMA_REVISION
            and set(fingerprint['tables']) == set(metadata.tables))
    body = {key: item for key, item in fingerprint.items() if key != 'evidence_sha256'}
    require(hashlib.sha256(canonical(body)).hexdigest() == fingerprint['evidence_sha256'])
    return value


def compare(source: dict, restored: dict, *, target_lsn: str, replay_lsn: str) -> dict:
    require(all(re.fullmatch(r'[0-9A-F]{1,8}/[0-9A-F]{1,8}', value)
                for value in (target_lsn, replay_lsn)))
    checked_snapshot(source, restored=False)
    checked_snapshot(restored, restored=True)
    require(restored['database_state']['target_lsn'] == target_lsn)
    # The reviewed target is a WAL record start; replay_lsn is that record's end.
    require(restored['database_state']['replay_lsn'] == replay_lsn)
    require(source['fingerprint'] == restored['fingerprint'])
    return {'contract': CONTRACT, 'status': 'workspace_restored_at_verified_record',
            'target_lsn': target_lsn, 'replay_lsn': replay_lsn,
            'schema_revision': EXPECTED_SCHEMA_REVISION, 'table_count': len(metadata.tables),
            'source_sha256': hashlib.sha256(canonical(source)).hexdigest(),
            'restored_sha256': hashlib.sha256(canonical(restored)).hexdigest(),
            'aggregate_sha256': source['fingerprint']['aggregate_sha256'],
            'fingerprint_compared': True, 'nonadmin_login_verified': True,
            'read_only_measurements': True, 'application_activated': False,
            'external_state_reconciled': False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('source', 'restored', 'compare'))
    parser.add_argument('--source', type=Path)
    parser.add_argument('--restored', type=Path)
    parser.add_argument('--target-lsn')
    parser.add_argument('--replay-lsn')
    args = parser.parse_args()
    if args.action == 'compare':
        require(args.source is not None and args.restored is not None)
        result = compare(json.loads(args.source.read_bytes()), json.loads(args.restored.read_bytes()),
                         target_lsn=args.target_lsn, replay_lsn=args.replay_lsn)
    else:
        require(args.source is None and args.restored is None
                and args.target_lsn is None and args.replay_lsn is None)
        result = measure(os.environ['DATABASE_URL'], restored=args.action == 'restored')
    print(canonical(result).decode())


if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit('Workspace restore proof refused; no application activated.') from None
