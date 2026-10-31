"""Read-only external-data gate for the two fixed enrollment staging domains."""
import hashlib
import json
import re
import shlex
import subprocess
import sys

HOSTS = {"onboarding.staging.cosmas.ai", "enrollment-api.staging.cosmas.ai"}
RESOLVERS = ("1.1.1.1", "8.8.8.8")


def verify(query, run=subprocess.run):
    if not isinstance(query, dict) or set(query) != {"hostname", "cname_target", "verification_id"}:
        raise ValueError("Invalid DNS binding input")
    hostname, target, token = (query[name] for name in ("hostname", "cname_target", "verification_id"))
    if (hostname not in HOSTS or not isinstance(target, str)
        or not re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)*\.azurecontainerapps\.io", target)
        or not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9._~=-]{8,512}", token)):
        raise ValueError("DNS binding must name the fixed owned host and its exact Azure app records")
    for resolver in RESOLVERS:
        for record_type, name, expected in (("CNAME", hostname, target), ("TXT", "asuid." + hostname, token)):
            answer = run(["dig", "+time=3", "+tries=1", "+noall", "+answer", "@" + resolver,
                          name, record_type], capture_output=True, text=True, timeout=5, check=True).stdout
            values = []
            for line in answer.splitlines():
                fields = line.split(None, 4)
                if len(fields) != 5 or fields[0].lower().rstrip(".") != name or fields[2] != "IN" or fields[3] != record_type:
                    continue
                value = fields[4].lower().rstrip(".") if record_type == "CNAME" else "".join(shlex.split(fields[4]))
                values.append(value)
            if (record_type == "CNAME" and values != [expected]) or (record_type == "TXT" and expected not in values):
                raise ValueError("Exact public CNAME/asuid TXT records are not propagated at both resolvers")
    records_hash = hashlib.sha256(json.dumps(query, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"verified": "true", "hostname": hostname, "records_sha256": records_hash,
            "resolvers": ",".join(RESOLVERS)}


if __name__ == "__main__":
    try:
        json.dump(verify(json.load(sys.stdin)), sys.stdout)
        sys.stdout.write("\n")
    except (ValueError, TypeError, OSError, subprocess.SubprocessError):
        sys.stderr.write("Staging DNS check failed; publish and verify the exact CNAME/asuid records before requesting TLS.\n")
        sys.exit(1)
