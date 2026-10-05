"""Build-only guard: remove exactly nonessential mount, preserve every other package."""
import importlib
import json
import subprocess


def packages():
    text = subprocess.check_output(['dpkg-query','-W','-f=${binary:Package}\t${Version}\t${Essential}\t${db:Status-Status}\n'], text=True)
    return {p[0]: dict(zip(['version','essential','status'],p[1:])) for row in text.splitlines() if len(p := row.split('\t')) == 4 and p[3] == 'installed'}


before = packages()
assert before['mount']['essential'] == 'no'
solver = subprocess.run(['apt-get','--simulate','purge','mount'], text=True, capture_output=True, check=True)
removals = [line for line in solver.stdout.splitlines() if line.startswith(('Remv ','Purg '))]
assert len(removals) == 1 and removals[0].startswith('Purg mount '), removals
assert 'WARNING:' not in solver.stdout and not solver.stderr.strip()
subprocess.run(['apt-get','--yes','purge','mount'], check=True)
after = packages()
assert 'mount' not in after and {k:v for k,v in before.items() if k != 'mount'} == after
for module in ['_uuid','_curses','ssl','sqlite3','cryptography','pypdf','psycopg','fastapi','cosmas_os.api.app']:
    importlib.import_module(module)
print(json.dumps({'removed':['mount'],'other_packages_identical':True,'essential_packages_retained':True,'before_packages':len(before),'after_packages':len(after)}))
