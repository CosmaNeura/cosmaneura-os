"""Exact canonical allocated-host DNS ownership, with no other zone mutations."""
from __future__ import annotations

import re
import shlex
import subprocess
import time

import httpx

from .hosting import HostingConfiguration, private_read


def bind_allocated_dns(config: HostingConfiguration, deployment: dict, resources: dict, tokens: dict,
                       *, client=None, run=subprocess.run, sleep=time.sleep):
    if not config.value["enabled"]:
        raise ValueError("private hosting DNS is disabled")
    plan = deployment["practice"]["plan"]
    practice = plan["practice_id"]
    domain = config.environment.workspace_domain
    hosts = {"web": practice + "." + domain, "api": "api." + practice + "." + domain}
    if (plan["workspace_url"] != "https://" + hosts["web"] + "/chief"
            or plan["api_origin"] != "https://" + hosts["api"] or set(tokens) != {"web", "api"}):
        raise ValueError("only this registered practice's paired DNS hosts are allowed")
    selected = []
    for kind in ("api", "web"):
        target, verification = resources[kind + "_fqdn"], tokens[kind]
        if (not isinstance(target, str) or not re.fullmatch(r"[a-z0-9-]+(?:[.][a-z0-9-]+)*[.]azurecontainerapps[.]io", target)
                or not isinstance(verification, str) or not re.fullmatch(r"[A-Za-z0-9._~=-]{8,512}", verification)):
            raise ValueError("actual allocated app DNS ownership records required")
        selected.extend([("CNAME", hosts[kind], target), ("TXT", "asuid." + hosts[kind], verification)])
    token = private_read(config.token_file, 4096).decode().strip()
    if not token or any(ord(char) < 33 or ord(char) > 126 for char in token):
        raise ValueError("protected zone-scoped provider credential required")
    owned = client or httpx.Client(timeout=15, follow_redirects=False)
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    zone = config.value["cloudflare_zone_id"]
    base = "https://api.cloudflare.com/client/v4/zones/" + zone

    def result(response):
        response.raise_for_status()
        value = response.json()
        if value.get("success") is not True:
            raise RuntimeError("owned DNS provider operation pending")
        return value["result"]

    actual = result(owned.get(base, headers=headers))
    if actual.get("id") != zone or actual.get("name") != "cosmas.ai":
        raise ValueError("the provider account does not own the selected Cosmas zone")
    # Validate every existing record before the first write. Foreign ownership
    # or replacement-app records require host review, never silent overwrite.
    missing = []
    for kind, host, content in selected:
        records = result(owned.get(base + "/dns_records", headers=headers, params={"name": host, "type": kind}))
        if not isinstance(records, list) or len(records) > 1:
            raise ValueError("ambiguous allocated DNS record")
        if records:
            row = records[0]
            if (row.get("type") != kind or row.get("name") != host or row.get("content") != content
                    or kind == "CNAME" and row.get("proxied") is not False):
                raise ValueError("allocated DNS hostname already belongs to a different binding")
        else:
            missing.append((kind, host, content))
    for kind, host, content in missing:
        body = {"type": kind, "name": host, "content": content, "ttl": 300}
        if kind == "CNAME":
            body["proxied"] = False
        row = result(owned.post(base + "/dns_records", headers=headers, json=body))
        if row.get("name") != host or row.get("type") != kind or row.get("content") != content:
            raise ValueError("DNS provider created a different record")
    for _ in range(18):
        ready = True
        for resolver in ("1.1.1.1", "8.8.8.8"):
            for kind, host, expected in selected:
                answer = run(["dig", "+time=3", "+tries=1", "+noall", "+answer", "@" + resolver, host, kind],
                             capture_output=True, text=True, timeout=5, check=True).stdout
                values = []
                for line in answer.splitlines():
                    fields = line.split(None, 4)
                    if len(fields) == 5 and fields[0].lower().rstrip(".") == host and fields[2:4] == ["IN", kind]:
                        values.append(fields[4].lower().rstrip(".") if kind == "CNAME" else "".join(shlex.split(fields[4])))
                if kind == "CNAME" and values != [expected] or kind == "TXT" and expected not in values:
                    ready = False
        if ready:
            return
        sleep(10)
    raise RuntimeError("exact allocated DNS ownership is still propagating")
