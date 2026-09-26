#!/usr/bin/python3
"""Host-only WAL-G controller. No credential, database-value or raw tool output is printed."""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import ipaddress
import json
import os
import platform
import pwd
import re
import socket
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

WALG = Path('/opt/cosmabot/backup/wal-g')
WALG_SHA256 = 'd6795c663894d836ba20840bffe8970aed81bbe25d3151bd4951f6f9c362def9'
WALG_SOURCE = '3e493188db28335fb93a45bd680c6ff8fc3028c1'
ROOT = Path('/etc/cosmabot/backup')
STATE = Path('/var/lib/cosmabot-backup')
RESTORE = Path('/var/lib/cosmabot-restore')
PSQL = '/usr/lib/postgresql/16/bin/psql'
PG = '/usr/lib/postgresql/16/bin/postgres'
SEGMENT_SIZE = 16 * 1024 * 1024
CONTRACT = 'cosmabot-walg-remote-pg16-v1'
COMMON_KEYS = {
    'version', 'mode', 'generation', 'system_identifier', 'timeline',
    'storage_account', 'storage_private_ip', 'tenant_id', 'client_id',
    'postgres_ca_sha256',
}
RESTORE_KEYS = {'restore_id', 'receipt_sha256', 'target_lsn', 'restore_certificate_sha256'}
BASE_ENV = {'PATH': '/usr/bin:/bin', 'LANG': 'C', 'LC_ALL': 'C', 'TZ': 'UTC'}


class Refused(RuntimeError):
    """Constant messages only: underlying tool diagnostics stay private."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Refused(message)


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def read_file(path: Path, *, owner: int = 0, private: bool = False,
              limit: int = 1024 * 1024) -> bytes:
    require(path.is_absolute() and path.resolve() == path, 'noncanonical input')
    for parent in path.parents:
        metadata = parent.stat()
        require(metadata.st_uid in {0, owner} and not metadata.st_mode & 0o022,
                'writable input parent')
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
        metadata = os.fstat(stream.fileno())
        require(stat.S_ISREG(metadata.st_mode) and metadata.st_uid == owner
                and metadata.st_nlink == 1 and metadata.st_size <= limit
                and not metadata.st_mode & (0o077 if private else 0o022), 'input custody')
        return stream.read(limit + 1)


def new_file(path: Path, raw: bytes) -> None:
    require(path.parent.resolve() == path.parent, 'output parent')
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def validate_config(value: dict) -> dict:
    mode = value.get('mode')
    require(mode in {'backup', 'restore'} and set(value) == COMMON_KEYS |
            (RESTORE_KEYS if mode == 'restore' else set()), 'configuration keys')
    require(type(value['version']) is int and value['version'] == 1, 'configuration version')
    require(re.fullmatch(r'[a-z][a-z0-9-]{5,63}', value['generation']) is not None,
            'cluster generation')
    require(re.fullmatch(r'[1-9][0-9]{17,19}', value['system_identifier']) is not None
            and int(value['system_identifier']) < 2**64, 'cluster identifier')
    require(type(value['timeline']) is int and 1 <= value['timeline'] < 2**32, 'timeline')
    require(re.fullmatch(r'[a-z0-9]{3,24}', value['storage_account']) is not None, 'storage account')
    address = ipaddress.ip_address(value['storage_private_ip'])
    require(address.version == 4 and address in ipaddress.ip_network('10.0.0.0/8'),
            'private blob address')
    for key in ('tenant_id', 'client_id'):
        require(str(uuid.UUID(value[key])) == value[key] and uuid.UUID(value[key]).int != 0,
                'identity identifier')
    require(re.fullmatch(r'[a-f0-9]{64}', value['postgres_ca_sha256']) is not None, 'CA hash')
    if mode == 'restore':
        require(re.fullmatch(r'[a-z][a-z0-9-]{5,63}', value['restore_id']) is not None, 'restore ID')
        require(re.fullmatch(r'[a-f0-9]{64}', value['receipt_sha256']) is not None, 'receipt hash')
        require(re.fullmatch(r'[a-f0-9]{64}', value['restore_certificate_sha256']) is not None,
                'restore certificate hash')
        lsn_number(value['target_lsn'])
    return value


def binding(config: dict) -> dict:
    return {key: config[key] for key in ('generation', 'system_identifier', 'timeline', 'storage_account')}


def prefix(config: dict) -> str:
    return 'azure://postgres-backups/cosmabot/' + config['generation'] + '/' + config['system_identifier']


def walg(*arguments: str) -> list[str]:
    return [str(WALG), '--config', str(ROOT / 'walg.json'), *arguments]


def lsn_number(value: str) -> int:
    require(isinstance(value, str) and re.fullmatch(r'[0-9A-F]{1,8}/[0-9A-F]{1,8}', value) is not None,
            'LSN syntax')
    high, low = value.split('/')
    return (int(high, 16) << 32) + int(low, 16)


def lsn_text(value: int) -> str:
    return f'{value >> 32:X}/{value & 0xFFFFFFFF:X}'


def segment_number(value: str, timeline: int) -> int:
    require(isinstance(value, str) and re.fullmatch(r'[0-9A-F]{24}', value) is not None,
            'WAL filename')
    require(int(value[:8], 16) == timeline and int(value[16:], 16) < 256, 'WAL timeline/size')
    return int(value[8:16], 16) * 256 + int(value[16:], 16)


def segment_name(number: int, timeline: int) -> str:
    return f'{timeline:08X}{number // 256:08X}{number % 256:08X}'


def verify_coverage(result: dict, start: int, finish: int, timeline: int) -> None:
    """Do not equate WAL-G's exit code, WARNING, or an empty OK result with coverage."""
    integrity = result.get('integrity', {})
    require(integrity.get('status') == 'OK', 'WAL coverage incomplete')
    ranges = integrity.get('details')
    require(isinstance(ranges, list) and bool(ranges), 'empty WAL coverage')
    next_segment = start
    for item in ranges:
        require(item.get('status') == 'FOUND' and item.get('timeline_id') == timeline,
                'missing or foreign WAL')
        first = segment_number(item['start_segment'], timeline)
        last = segment_number(item['end_segment'], timeline)
        require(type(item.get('segments_count')) is int and first == next_segment and last >= first and
                item.get('segments_count') == last - first + 1, 'discontinuous WAL coverage')
        next_segment = last + 1
    require(next_segment == finish + 1, 'WAL coverage endpoint')


def backup_metadata(item: dict, config: dict) -> dict:
    name = item.get('backup_name')
    require(isinstance(name, str) and re.fullmatch(r'base_[0-9A-F]{24}', name) is not None,
            'full backup name')
    start, finish = item.get('start_lsn'), item.get('finish_lsn')
    require(type(start) is int and type(finish) is int and 0 < start <= finish < 2**64,
            'backup LSN metadata')
    require(type(item.get('system_identifier')) is int and
            str(item['system_identifier']) == config['system_identifier'], 'backup cluster mismatch')
    require(type(item.get('pg_version')) is int and 160000 <= item['pg_version'] < 170000,
            'backup PostgreSQL major')
    require(item.get('wal_file_name') == name[5:] and
            segment_number(name[5:], config['timeline']) == start // SEGMENT_SIZE,
            'backup start mismatch')
    user = item.get('user_data')
    require(isinstance(user, dict) and set(user) == {'contract', 'cluster', 'job_id'}
            and user['contract'] == CONTRACT and user['cluster'] == binding(config)
            and str(uuid.UUID(user['job_id'])) == user['job_id'], 'backup namespace provenance')
    # Select only public metadata. Never publish filesystem paths, file manifests or raw output.
    return {'backup_name': name, 'start_lsn': start, 'finish_lsn': finish,
            'system_identifier': str(item['system_identifier']), 'timeline': config['timeline'],
            'user_data': user}


def clean_environment(config: dict, credentials: Path) -> dict[str, str]:
    # Reject caller attempts, then build from scratch. No config files/home/CLI/MI fallback.
    forbidden = ('AZURE_', 'WALG_', 'WALE_', 'PG', 'AWS_', 'GOOGLE_', 'GCS_', 'S3_', 'LD_', 'DYLD_')
    require(not any(key.startswith(forbidden) or key.upper().endswith('_PROXY')
                    for key in os.environ), 'ambient credential/config override')
    env = dict(BASE_ENV)
    env.update({
        'HOME': '/nonexistent', 'AZURE_TOKEN_CREDENTIALS': 'EnvironmentCredential',
        'AZURE_TENANT_ID': config['tenant_id'], 'AZURE_CLIENT_ID': config['client_id'],
        'AZURE_CLIENT_CERTIFICATE_PATH': str(credentials / 'azure.pem'),
        'AZURE_STORAGE_ACCOUNT': config['storage_account'], 'WALG_AZ_PREFIX': prefix(config),
        'WALG_DELTA_MAX_STEPS': '0', 'WALG_UPLOAD_CONCURRENCY': '1',
        'WALG_DOWNLOAD_CONCURRENCY': '1', 'WALG_DOWNLOAD_FILE_RETRIES': '2',
        'AZURE_BUFFER_SIZE': '8388608', 'AZURE_MAX_BUFFERS': '2', 'AZURE_TRY_TIMEOUT': '1',
        'WALG_LOG_LEVEL': 'NORMAL',
    })
    if config['mode'] == 'backup':
        env.update({'PGHOST': 'postgres', 'PGPORT': '5432', 'PGDATABASE': 'postgres',
                    'PGUSER': 'cosmabot_backup', 'PGPASSFILE': str(credentials / 'pgpass'),
                    'PGSSLMODE': 'verify-full', 'PGSSLROOTCERT': str(ROOT / 'postgres-ca.pem'),
                    'PGCONNECT_TIMEOUT': '10', 'WALG_SLOTNAME': 'cosmabot_backup'})
    return env


QUERY = """
SELECT json_build_object(
 'system_identifier',(pg_control_system()).system_identifier::text,
 'timeline',(pg_control_checkpoint()).timeline_id,
 'version',current_setting('server_version_num')::int,
 'segment_bytes',pg_size_bytes(current_setting('wal_segment_size')),
 'wal_level',current_setting('wal_level'), 'archive_mode',current_setting('archive_mode'),
 'max_wal_senders',current_setting('max_wal_senders')::int,
 'max_replication_slots',current_setting('max_replication_slots')::int,
 'slot_limit_bytes',pg_size_bytes(current_setting('max_slot_wal_keep_size')),
 'recovery',pg_is_in_recovery(), 'server_addr',host(inet_server_addr()),
 'server_port',inet_server_port(), 'user',current_user,
 'ssl',(SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()),
 'role',(SELECT json_build_object('replication',rolreplication,'superuser',rolsuper,
     'createdb',rolcreatedb,'createrole',rolcreaterole,'bypassrls',rolbypassrls)
     FROM pg_roles WHERE rolname=current_user),
 'memberships',(SELECT coalesce(json_agg(r.rolname ORDER BY r.rolname),'[]')
     FROM pg_auth_members m JOIN pg_roles r ON m.roleid=r.oid
     WHERE m.member=(SELECT oid FROM pg_roles WHERE rolname=current_user)),
 'slot',(SELECT json_build_object('type',slot_type,'active',active,
     'restart_lsn',restart_lsn::text,'wal_status',wal_status,
     'retained_bytes',pg_wal_lsn_diff(pg_current_wal_lsn(),restart_lsn))
     FROM pg_replication_slots WHERE slot_name='cosmabot_backup'));
"""


def validate_database(info: dict, config: dict, *, receiver: bool = False) -> dict:
    require(info['system_identifier'] == config['system_identifier']
            and info['timeline'] == config['timeline'] and info['recovery'] is False,
            'wrong live cluster')
    require(160000 <= info['version'] < 170000 and info['segment_bytes'] == SEGMENT_SIZE
            and info['wal_level'] == 'replica' and info['archive_mode'] == 'off'
            and info['max_wal_senders'] >= 3 and info['max_replication_slots'] >= 2
            and info['slot_limit_bytes'] == 4096 * 1024 * 1024, 'PostgreSQL backup settings')
    require(info['server_addr'] == '172.30.240.20' and info['server_port'] == 5432
            and info['ssl'] is True and info['user'] == 'cosmabot_backup', 'PostgreSQL target/TLS')
    require(info['role'] == {'replication': True, 'superuser': False, 'createdb': False,
                             'createrole': False, 'bypassrls': False}
            and info['memberships'] == ['pg_read_all_settings'], 'replication role scope')
    slot = info['slot']
    require(isinstance(slot, dict) and slot['type'] == 'physical' and slot['restart_lsn']
            and slot['wal_status'] in {'reserved', 'extended'}
            and 0 <= slot['retained_bytes'] < 3 * 1024 * 1024 * 1024,
            'slot invalid or lag excessive; new baseline may be required')
    lsn_number(slot['restart_lsn'])
    require(slot['active'] is (False if receiver else True), 'receiver slot ownership')
    return info


class Runner:
    def __init__(self, config: dict):
        self.config = config
        self.directory = STATE if config['mode'] == 'backup' else RESTORE
        self.env: dict[str, str] = {}

    def call(self, args: list[str], *, timeout: int = 120, capture: bool = True) -> bytes:
        # stderr is never returned, even on failure. Logs are private and rotated by logrotate.
        with (self.directory / 'commands.log').open('ab') as log, tempfile.TemporaryFile() as output:
            result = subprocess.run(args, env=self.env, cwd=self.directory,
                                    stdout=output if capture else log, stderr=log,
                                    timeout=timeout, check=False)
            require(result.returncode == 0, 'host command failed; inspect protected log')
            if capture:
                output.seek(0)
                raw = output.read(16 * 1024 * 1024 + 1)
                require(len(raw) <= 16 * 1024 * 1024, 'command output too large')
                return raw
        return b''

    def sql(self, query: str) -> dict:
        return json.loads(self.call([PSQL, '-X', '--no-password', '-A', '-t',
                                     '-v', 'ON_ERROR_STOP=1', '-c', query], timeout=30))

    def preflight(self) -> None:
        mode = self.config['mode']
        require(platform.system() == 'Linux' and platform.machine() == 'x86_64', 'native host required')
        user = 'cosmabot-backup' if mode == 'backup' else 'cosmabot-restore'
        identity = pwd.getpwnam(user)
        require(os.geteuid() == identity.pw_uid and os.geteuid() != 0
                and os.getegid() == identity.pw_gid
                and set(os.getgroups()) <= {identity.pw_gid}, 'dedicated host account')
        require(self.directory.resolve() == self.directory
                and self.directory.stat().st_uid == os.geteuid()
                and stat.S_IMODE(self.directory.stat().st_mode) == 0o700, 'state directory custody')
        credentials = Path(os.environ.get('CREDENTIALS_DIRECTORY', '/missing'))
        action = os.environ.get('COSMABOT_BACKUP_ACTION', '')
        unit = ('cosmabot-restore.service' if mode == 'restore' else
                ('cosmabot-backup-receive.service' if action == 'receive' else
                 'cosmabot-backup-job@' + action + '.service'))
        expected = '/run/credentials/' + unit
        require(str(credentials) == expected, 'systemd credential path')
        read_file(credentials / 'azure.pem', owner=os.geteuid(), private=True, limit=32768)
        self.env = clean_environment(self.config, credentials)
        require(read_file(ROOT / 'walg.json') == b'{}\n', 'closed WAL-G configuration')
        require(sha(read_file(WALG, limit=70 * 1024 * 1024)) == WALG_SHA256, 'WAL-G binary digest')
        version = self.call(walg('--version')).decode()
        require('v3.0.9' in version or '3.0.9' in version, 'WAL-G version')
        self.call(['/usr/bin/openssl', 'x509', '-in', str(credentials / 'azure.pem'),
                   '-noout', '-checkend', '604800'])
        blob_host = self.config['storage_account'] + '.blob.core.windows.net'
        addresses = {entry[4][0] for entry in socket.getaddrinfo(blob_host, 443, type=socket.SOCK_STREAM)}
        require(addresses == {self.config['storage_private_ip']}, 'private blob resolution')
        if mode == 'backup':
            require(platform.node() == 'vm-cosmabot-staging-eus2-lab01', 'backup host binding')
            require(sha(read_file(ROOT / 'postgres-ca.pem')) == self.config['postgres_ca_sha256'],
                    'PostgreSQL CA binding')
            addresses = {entry[4][0] for entry in socket.getaddrinfo(
                'postgres', 5432, type=socket.SOCK_STREAM)}
            require(addresses == {'172.30.240.20'}, 'PostgreSQL DNS binding')
            raw = read_file(credentials / 'pgpass', owner=os.geteuid(), private=True, limit=1024)
            rows = raw.decode().splitlines()
            require(len(rows) == 2, 'passfile entries')
            passwords = []
            for row, database in zip(rows, ('postgres', 'replication')):
                fields = row.split(':')
                require(len(fields) == 5 and fields[:4] == ['postgres', '5432', database, 'cosmabot_backup']
                        and re.fullmatch(r'[A-Za-z0-9_-]{32,128}', fields[4]) is not None, 'passfile scope')
                passwords.append(fields[4])
            require(passwords[0] == passwords[1], 'passfile mismatch')

    def database(self, *, receiver: bool = False) -> dict:
        return validate_database(self.sql(QUERY), self.config, receiver=receiver)

    def listing(self) -> list[dict]:
        values = json.loads(self.call(walg('backup-list', '--detail', '--json')))
        require(isinstance(values, list), 'backup listing')
        return [backup_metadata(value, self.config) for value in values]

    def coverage(self, name: str, start: int, finish: int) -> dict:
        # Pinned v3.0.9 uses floor((lsn-1)/S), then scans the preceding segment.
        endpoint = (finish + 1) * SEGMENT_SIZE + 1
        result = json.loads(self.call(walg('wal-verify', 'integrity', '--backup-name', name,
                                          '--timeline', str(self.config['timeline']),
                                          '--lsn', lsn_text(endpoint),
                                          '--json')))
        verify_coverage(result, start, finish, self.config['timeline'])
        return result

    def backup(self) -> dict:
        self.database()
        existing = {item['backup_name'] for item in self.listing()}
        job_id = str(uuid.uuid4())
        self.env['WALG_SENTINEL_USER_DATA'] = canonical(
            {'contract': CONTRACT, 'cluster': binding(self.config), 'job_id': job_id}).decode()
        # No PGDATA and no directory argument: this selects BASE_BACKUP, never live-file access.
        self.call(walg('backup-push'), timeout=7200, capture=False)
        items = [item for item in self.listing() if item['user_data']['job_id'] == job_id
                 and item['backup_name'] not in existing]
        require(len(items) == 1, 'new completed base not uniquely identified')
        item = items[0]
        self.database()
        self.sql('SELECT to_json(pg_switch_wal()::text);')
        start, finish = item['start_lsn'] // SEGMENT_SIZE, item['finish_lsn'] // SEGMENT_SIZE
        deadline = time.monotonic() + 300
        while True:
            try:
                coverage = self.coverage(item['backup_name'], start, finish)
                break
            except Refused:
                require(time.monotonic() < deadline, 'base uploaded but WAL coverage not complete')
                time.sleep(5)
                self.database()
        receipt = {'contract': CONTRACT, 'status': 'base_and_wal_presence_verified', 'at': utc(),
                   'cluster': binding(self.config), 'prefix': prefix(self.config), 'backup': item,
                   'writer_client_id': self.config['client_id'], 'tenant_id': self.config['tenant_id'],
                   'first_wal': segment_name(start, self.config['timeline']),
                   'last_wal': segment_name(finish, self.config['timeline']),
                   'wal_verify_sha256': sha(canonical(coverage)), 'metadata_sha256': sha(canonical(item)),
                   'wal_g_sha256': WALG_SHA256, 'wal_g_source': WALG_SOURCE,
                   'restore_qualified': False, 'retention_enabled': False}
        new_file(self.directory / (item['backup_name'] + '.json'), canonical(receipt) + b'\n')
        return receipt

    def status(self) -> dict:
        database = self.database()
        receipts = sorted(self.directory.glob('base_*.json'), key=lambda path: path.stat().st_mtime)
        require(bool(receipts), 'no completed base receipt')
        receipt = json.loads(read_file(receipts[-1], owner=os.geteuid(), private=True))
        require(receipt['cluster'] == binding(self.config), 'receipt cluster mismatch')
        age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(receipt['at'])).total_seconds()
        require(0 <= age <= 90000, 'completed base stale')
        current = self.sql('SELECT to_json(pg_current_wal_lsn()::text);')
        # Only completed segments can be present. The switch timer forces a new segment each minute.
        finish = lsn_number(current) // SEGMENT_SIZE - 1
        start = receipt['backup']['start_lsn'] // SEGMENT_SIZE
        self.coverage(receipt['backup']['backup_name'], start, finish)
        return {'status': 'current_completed_wal_present', 'at': utc(),
                'cluster': binding(self.config),
                'last_completed_wal': segment_name(finish, self.config['timeline']),
                'base_age_seconds': int(age), 'slot_retained_bytes': database['slot']['retained_bytes'],
                'restore_qualified': False}


def locked(path: Path) -> int:
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    metadata = os.fstat(descriptor)
    require(stat.S_ISREG(metadata.st_mode) and metadata.st_uid == os.geteuid()
            and metadata.st_nlink == 1 and stat.S_IMODE(metadata.st_mode) == 0o600, 'lock custody')
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return descriptor


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('receive', 'backup', 'switch', 'status'))
    args = parser.parse_args()
    os.umask(0o077)
    config = validate_config(json.loads(read_file(ROOT / 'backup.json')))
    require(config['mode'] == 'backup' and os.environ.get('COSMABOT_BACKUP_ACTION') == args.action,
            'service action binding')
    runner = Runner(config)
    runner.preflight()
    descriptor = locked(STATE / (args.action + '.lock'))
    try:
        if args.action == 'receive':
            runner.database(receiver=True)
            # Keep the receiver lock across exec; systemd owns signals and the entire cgroup.
            os.set_inheritable(descriptor, True)
            os.chdir(STATE)
            os.execve(WALG, walg('wal-receive'), runner.env)
        elif args.action == 'backup':
            print(canonical(runner.backup()).decode())
        elif args.action == 'switch':
            runner.database()
            runner.sql('SELECT to_json(pg_switch_wal()::text);')
            print(canonical({'status': 'wal_switch_requested', 'at': utc()}).decode())
        else:
            print(canonical(runner.status()).decode())
    finally:
        os.close(descriptor)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('Backup operation refused or incomplete; inspect the protected service log.', file=sys.stderr)
        raise SystemExit(1) from None
