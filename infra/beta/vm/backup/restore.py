#!/usr/bin/python3
"""Fetch one reviewed backup into a fresh isolated directory; recover only to a fixed LSN."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# Explicit adjacent root-owned module works with Python -I (no cwd/PYTHONPATH import).
spec = importlib.util.spec_from_file_location('cosmabot_backup', Path(__file__).with_name('backup.py'))
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


def target_path(config: dict) -> Path:
    return backup.RESTORE / config['restore_id'] / 'data'


CONTROL_SETTINGS = {
    'max_connections setting': 'max_connections',
    'max_worker_processes setting': 'max_worker_processes',
    'max_wal_senders setting': 'max_wal_senders',
    'max_prepared_xacts setting': 'max_prepared_transactions',
    'max_locks_per_xact setting': 'max_locks_per_transaction',
}


def recovery_settings(control: str, system_identifier: str) -> dict[str, int]:
    """PG16 hot standby must meet the restored control file's source settings.

    PostgreSQL xlog.c CheckRequiredParameterValues checks these five values,
    including again when parameter changes are replayed. Do not lower them to
    fit a resource budget: refuse the restore or provision an adequate target.
    """
    observed = {}
    for line in control.splitlines():
        if ':' not in line:
            continue
        key, value = (part.strip() for part in line.split(':', 1))
        backup.require(key not in observed, 'duplicate control field')
        observed[key] = value
    backup.require(observed.get('Database system identifier') == system_identifier,
                   'restored cluster identifier')
    backup.require(observed.get('wal_level setting') in {'replica', 'logical'},
                   'source does not support hot standby')
    settings = {}
    for label, setting in CONTROL_SETTINGS.items():
        value = observed.get(label, '')
        backup.require(re.fullmatch(r'[0-9]{1,10}', value) is not None,
                       'missing or invalid source recovery setting')
        number = int(value)
        backup.require(number <= 2**31 - 1 and
                       (number > 0 if setting in {'max_connections',
                        'max_locks_per_transaction'} else number >= 0),
                       'source recovery setting range')
        settings[setting] = number
    return settings


def recovery_configuration(config: dict, credentials: Path, settings: dict[str, int]) -> str:
    job = target_path(config).parent
    # All interpolated values pass strict public-config validation or are fixed paths.
    return f"""data_directory = '{job}/data'
hba_file = '{job}/pg_hba.conf'
ident_file = '{job}/pg_ident.conf'
listen_addresses = '127.0.0.1'
port = 55432
unix_socket_directories = '{job}/socket'
ssl = on
ssl_ca_file = '{backup.ROOT}/postgres-ca.pem'
ssl_cert_file = '{backup.ROOT}/restore-server.crt'
ssl_key_file = '{credentials}/server.key'
archive_mode = off
archive_command = ''
primary_conninfo = ''
primary_slot_name = ''
restore_command = '/usr/bin/python3 -I /opt/cosmabot/backup/restore.py wal %f %p'
recovery_target_lsn = '{config['target_lsn']}'
recovery_target_timeline = '{config['timeline']}'
recovery_target_inclusive = on
recovery_target_action = pause
hot_standby = on
default_transaction_read_only = on
shared_preload_libraries = ''
shared_buffers = '128MB'
{''.join(f'{key} = {value}' + chr(10) for key, value in settings.items())}
"""


def checked_receipt(config: dict, raw: bytes) -> dict:
    backup.require(backup.sha(raw) == config['receipt_sha256'], 'reviewed receipt digest')
    value = json.loads(raw)
    backup.require(value['contract'] == backup.CONTRACT
                   and value['status'] == 'base_and_wal_presence_verified'
                   and value['cluster'] == backup.binding(config)
                   and value['prefix'] == backup.prefix(config)
                   and value['tenant_id'] == config['tenant_id']
                   and value['writer_client_id'] != config['client_id']
                   and value['wal_g_sha256'] == backup.WALG_SHA256
                   and value['metadata_sha256'] == backup.sha(backup.canonical(value['backup'])),
                   'restore receipt binding')
    backup.require(backup.lsn_number(config['target_lsn']) >= value['backup']['finish_lsn'],
                   'target before base finish')
    return value


def fetch(runner: backup.Runner) -> Path:
    config = runner.config
    receipt = checked_receipt(config, backup.read_file(backup.ROOT / 'restore-receipt.json'))
    matches = [item for item in runner.listing() if item['backup_name'] == receipt['backup']['backup_name']]
    backup.require(matches == [receipt['backup']], 'remote backup metadata changed')
    target = target_path(config)
    job = target.parent
    backup.require(not job.exists() and not job.is_symlink(), 'restore target must be fresh')
    job.mkdir(mode=0o700)
    target.mkdir(mode=0o700)
    runner.call(backup.walg('backup-fetch', str(target), receipt['backup']['backup_name']),
                timeout=7200, capture=False)
    backup.require(backup.read_file(target / 'PG_VERSION', owner=os.geteuid()).strip() == b'16',
                   'restored PostgreSQL major')
    # No tablespace links may lead outside this new target, and no archived configuration is executed.
    backup.require(not any((target / 'pg_tblspc').iterdir()), 'external tablespaces unsupported')
    for name in ('postgresql.auto.conf', 'standby.signal', 'recovery.signal'):
        source = target / name
        if source.exists() or source.is_symlink():
            backup.read_file(source, owner=os.geteuid())
            source.rename(job / ('archived-' + name))
    backup.new_file(target / 'postgresql.auto.conf', b'')
    backup.new_file(target / 'recovery.signal', b'')
    (job / 'socket').mkdir(mode=0o700)
    backup.new_file(job / 'pg_hba.conf', b'local postgres postgres peer map=cosmabot_restore\n'
                    b'hostssl cosmas_os cosmas 127.0.0.1/32 scram-sha-256\n'
                    b'local all all reject\nhost all all 0.0.0.0/0 reject\nhost all all ::0/0 reject\n')
    backup.new_file(job / 'pg_ident.conf', b'cosmabot_restore cosmabot-restore postgres\n')
    control = runner.call(['/usr/lib/postgresql/16/bin/pg_controldata', str(target)]).decode()
    settings = recovery_settings(control, config['system_identifier'])
    backup.new_file(job / 'postgresql.conf', recovery_configuration(
        config, Path(os.environ['CREDENTIALS_DIRECTORY']), settings).encode())
    backup.new_file(job / 'FETCH.json', backup.canonical({
        'status': 'fetched_not_recovered', 'at': backup.utc(), 'cluster': backup.binding(config),
        'backup_name': receipt['backup']['backup_name'], 'receipt_sha256': config['receipt_sha256'],
        'target_lsn': config['target_lsn'], 'recovery_settings': settings,
        'restore_qualified': False}) + b'\n')
    return target


def wal_fetch(runner: backup.Runner, name: str, destination: str) -> int:
    # PostgreSQL uses relative pg_wal/RECOVERYXLOG and also asks for .history/.backup files.
    backup.require(re.fullmatch(
        r'(?:[0-9A-F]{24}|[0-9A-F]{8}\.history|[0-9A-F]{24}\.[0-9A-F]{8}\.backup)', name)
                   is not None, 'archive filename')
    target = target_path(runner.config)
    path = Path(destination)
    if not path.is_absolute():
        path = Path.cwd() / path
    backup.require(Path.cwd() == target and path.parent == target / 'pg_wal'
                   and path.parent.resolve() == path.parent and not path.is_symlink(),
                   'WAL restore destination')
    with (backup.RESTORE / 'commands.log').open('ab') as log:
        result = subprocess.run(backup.walg('wal-fetch', name, str(path)), env=runner.env,
                                stdout=log, stderr=log, timeout=180, check=False)
    # 74 means a genuinely absent archive. All auth/network/configuration failures are fatal to PG.
    return 0 if result.returncode == 0 else (74 if result.returncode == 74 else 126)


def verify_paused(runner: backup.Runner) -> dict:
    job = target_path(runner.config).parent
    query = """SELECT json_build_object('recovery',pg_is_in_recovery(),
      'paused',pg_get_wal_replay_pause_state(),'lsn',pg_last_wal_replay_lsn()::text,
      'target',current_setting('recovery_target_lsn'),
      'timeline',current_setting('recovery_target_timeline'),
      'system_identifier',(pg_control_system()).system_identifier::text);"""
    env = dict(backup.BASE_ENV)
    env.update({'PGHOST': str(job / 'socket'), 'PGPORT': '55432', 'PGUSER': 'postgres',
                'PGDATABASE': 'postgres', 'PGCONNECT_TIMEOUT': '10'})
    prior = runner.env
    runner.env = env
    try:
        result = runner.sql(query)
    finally:
        runner.env = prior
    backup.require(result['recovery'] is True and result['paused'] == 'paused'
                   and result['target'] == runner.config['target_lsn']
                   and result['timeline'] == str(runner.config['timeline'])
                   and result['system_identifier'] == runner.config['system_identifier']
                   and backup.lsn_number(result['lsn']) >= backup.lsn_number(result['target']),
                   'recovery target not demonstrably reached and paused')
    # Inclusive LSN targets compare record starts; the replay LSN is a record end.
    # This is an engine-state receipt, not proof that the expected data survived.
    receipt = {'status': 'fixed_target_reached_paused', 'at': backup.utc(),
               'cluster': backup.binding(runner.config), 'recovery': result,
               'fingerprint_compared': False, 'application_activated': False}
    backup.new_file(job / 'RECOVERY.json', backup.canonical(receipt) + b'\n')
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('run', 'wal', 'verify'))
    parser.add_argument('archive', nargs='?')
    parser.add_argument('destination', nargs='?')
    args = parser.parse_args()
    os.umask(0o077)
    config = backup.validate_config(json.loads(backup.read_file(backup.ROOT / 'restore.json')))
    backup.require(config['mode'] == 'restore', 'reader configuration required')
    if args.action == 'wal':
        # PostgreSQL adds these installation paths to archive-command children.
        # WAL-G needs neither; discard them before the closed environment check.
        for key in ('PGLOCALEDIR', 'PGSYSCONFDIR'):
            os.environ.pop(key, None)
    runner = backup.Runner(config)
    # ExecStartPost only inspects the local peer-authenticated PostgreSQL socket.
    # Its systemd credential namespace need not expose the cloud reader secret.
    if args.action == 'verify':
        runner.preflight_host()
    else:
        runner.preflight()
    if args.action == 'wal':
        return wal_fetch(runner, args.archive, args.destination)
    backup.require(args.archive is None and args.destination is None, 'unexpected arguments')
    if args.action == 'verify':
        deadline = time.monotonic() + 7500
        while True:
            try:
                result = verify_paused(runner)
                break
            except (backup.Refused, FileNotFoundError):
                backup.require(time.monotonic() < deadline, 'restore target wait expired')
                time.sleep(5)
        print(backup.canonical(result).decode())
        return 0
    descriptor = backup.locked(backup.RESTORE / 'restore.lock')
    os.set_inheritable(descriptor, True)
    credentials = Path(os.environ['CREDENTIALS_DIRECTORY'])
    backup.read_file(credentials / 'server.key', owner=os.geteuid(), private=True)
    backup.require(backup.sha(backup.read_file(backup.ROOT / 'postgres-ca.pem')) ==
                   config['postgres_ca_sha256']
                   and backup.sha(backup.read_file(backup.ROOT / 'restore-server.crt')) ==
                   config['restore_certificate_sha256'], 'restore TLS binding')
    runner.call(['/usr/bin/openssl', 'verify', '-x509_strict',
                 '-CAfile', str(backup.ROOT / 'postgres-ca.pem'),
                 '-verify_hostname', 'cosmabot-restore', str(backup.ROOT / 'restore-server.crt')])
    target = fetch(runner)
    # PostgreSQL/restore_command get no Azure env or application/deployment credential.
    env = dict(backup.BASE_ENV)
    env['CREDENTIALS_DIRECTORY'] = str(credentials)
    os.chdir(target)
    os.execve(backup.PG, [backup.PG, '-D', str(target), '-c',
                        'config_file=' + str(target.parent / 'postgresql.conf')], env)
    return 126


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        print('Restore refused or incomplete; inspect the protected service log.', file=sys.stderr)
        raise SystemExit(126) from None
