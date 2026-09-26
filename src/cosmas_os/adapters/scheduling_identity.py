"""Confirm a user-supplied Scheduling proof against its reviewed account.

The receiver owns token verification, membership and its internal actor identity.
This adapter never treats a Clerk token or matching email as a Scheduling grant.
"""

import json
import re
from time import monotonic
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from pydantic import SecretStr

from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.scheduling import SchedulingSelection


class SchedulingIdentityVerifier:
    def __init__(self, origin: str, *, transport: httpx.BaseTransport | None = None):
        parsed = urlsplit(origin)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.port not in {None, 443}
            or parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.hostname.endswith(".")
            or not re.fullmatch(r"https://[a-z0-9.-]+", origin)
            or origin != "https://" + parsed.hostname
        ):
            raise ValueError("A fixed HTTPS Scheduling origin is required")
        self._client = httpx.Client(
            base_url=origin,
            timeout=httpx.Timeout(10.0),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
            limits=httpx.Limits(max_connections=8, max_keepalive_connections=4),
        )
        self._closed = False

    def confirm(self, selection: SchedulingSelection, token: SecretStr) -> None:
        try:
            selected = SchedulingSelection.model_validate(selection.model_dump(warnings=False))
            if (
                self._closed
                or selected.expected_actor_id is None
                or not isinstance(token, SecretStr)
            ):
                raise ValueError
            value = token.get_secret_value()
            if not 1 <= len(value) <= 16_384 or any(ord(c) < 33 or ord(c) > 126 for c in value):
                raise ValueError
            deadline = monotonic() + 10
            with self._client.stream(
                "GET",
                "/v1/me/staff",
                headers={
                    "Authorization": "Bearer " + value,
                    "X-Practice-ID": str(selected.practice_id),
                    "Accept": "application/json",
                    "Accept-Encoding": "identity",
                    "Cache-Control": "no-store",
                },
            ) as response:
                if (
                    monotonic() >= deadline
                    or response.status_code != 200
                    or response.headers.get("content-encoding") not in {None, "identity"}
                    or response.headers.get("content-type", "").split(";", 1)[0]
                    != "application/json"
                ):
                    raise ValueError
                raw = bytearray()
                for chunk in response.iter_raw():
                    if monotonic() >= deadline or len(raw) + len(chunk) > 1024:
                        raise ValueError
                    raw.extend(chunk)
            if monotonic() >= deadline:
                raise ValueError

            def pairs(values):
                result = {}
                for name, value in values:
                    if name in result:
                        raise ValueError
                    result[name] = value
                return result

            data = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
            if (
                not isinstance(data, dict)
                or set(data) != {"practice_id", "actor_id", "role"}
                or data["practice_id"] != str(selected.practice_id)
                or data["actor_id"] != str(selected.expected_actor_id)
                or UUID(data["actor_id"]) != selected.expected_actor_id
                or data["role"] not in {"owner", "admin", "staff"}
                or self._closed
            ):
                raise ValueError
        except Exception:
            raise ConnectorUnavailable("scheduling_identity_unavailable") from None

    def close(self) -> None:
        self._closed = True
        self._client.close()

    def catalog(self, practice_id: UUID, token: SecretStr):
        """Read choices under receiver-owned current identity and membership."""
        from datetime import UTC, datetime, timedelta

        from cosmas_os.ports.scheduling_enrollment import MAX_CATALOG_BYTES, ConnectionCatalog
        try:
            value=token.get_secret_value()
            if self._closed or not 1<=len(value)<=16384 or any(ord(c)<33 or ord(c)>126 for c in value):
                raise ValueError
            deadline=monotonic()+10
            with self._client.stream("GET","/v1/me/companion-connection",headers={
                "Authorization":"Bearer "+value,"X-Practice-ID":str(practice_id),
                "X-Cosmaneura-Connection-Catalog":"1","Accept":"application/json",
                "Accept-Encoding":"identity","Cache-Control":"no-store",
            }) as response:
                if response.status_code!=200 or response.headers.get("content-encoding") not in {None,"identity"} or response.headers.get("content-type","").split(";",1)[0]!="application/json" or "no-store" not in response.headers.get("cache-control","").split(","):
                    raise ValueError
                raw=bytearray()
                for chunk in response.iter_raw():
                    if monotonic()>=deadline or len(raw)+len(chunk)>MAX_CATALOG_BYTES:
                        raise ValueError
                    raw.extend(chunk)
            def pairs(values):
                result={}
                for key,value in values:
                    if key in result:
                        raise ValueError
                    result[key]=value
                return result
            result=ConnectionCatalog.model_validate(json.loads(raw.decode("utf-8"),object_pairs_hook=pairs))
            now=datetime.now(UTC)
            if result.practice.id!=practice_id or not now-timedelta(seconds=30)<=result.observed_at<=now+timedelta(seconds=5) or monotonic()>=deadline or self._closed:
                raise ValueError
            return result
        except Exception:
            raise ConnectorUnavailable("scheduling_identity_unavailable") from None
