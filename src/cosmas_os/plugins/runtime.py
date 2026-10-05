"""Bounded authenticated HTTP execution; no lab fixtures or vendor credentials."""

import base64
import hashlib
import json
import os
import re
import stat
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from jsonschema import Draft202012Validator, FormatChecker

from cosmas_os.api.plugin_catalog import CONTRACT, META, definitions, tool

MAX_RESPONSE = 12_000_000
LEGACY = {"google.mail_headers", "google.calendar_summaries", "microsoft.mail_headers",
          "microsoft.calendar_summaries", "scheduling.read_availability", "scheduling.read_current",
          "scheduling.inspect_proposal", "scribe.read_existing", "visit_prep.read_brief",
          "spruce.prepare_delivery", "srfax.prepare_delivery", "documo.prepare_delivery", "efax.prepare_delivery"}
HEADERS = {"X-Cosmas-Workspace-Protocol": "1", "X-Cosmas-Draft-Recovery": "2"}


class PluginError(Exception):
    """Closed diagnostic; never include tokens, source text or provider errors."""


def pairs(values):
    result = {}
    for key, value in values:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def origin_checked(value):
    try:
        parsed = urlsplit(value)
        if (not isinstance(value, str) or not value.isascii() or re.search(r"[\s\\]", value)
                or parsed.scheme != "https" or not parsed.hostname or parsed.port not in (None, 443)
                or parsed.username or parsed.password or parsed.path not in ("", "/")
                or parsed.query or parsed.fragment):
            raise ValueError
        return value.rstrip("/")
    except (ValueError, TypeError):
        raise PluginError("invalid_api_origin") from None


def token_read(path):
    """Read a rotating owner-only file for each request; never persist the token."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as source:
            info = os.fstat(source.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_mode & 0o077 or info.st_size > 16384):
                raise ValueError
            value = source.read(16385).decode("ascii").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", value):
            raise ValueError
        return value
    except (OSError, ValueError, UnicodeError):
        raise PluginError("sign_in_required") from None


class PluginRuntime:
    def __init__(self, origin, token_file, *, workspace_id=None, plugins=(), transport=None):
        self.origin = origin_checked(origin)
        self.token_file = Path(token_file)
        if not self.token_file.is_absolute():
            raise PluginError("absolute_token_file_required")
        if workspace_id is not None:
            try:
                if str(UUID(workspace_id)) != workspace_id or UUID(workspace_id).int == 0:
                    raise ValueError
            except (ValueError, TypeError):
                raise PluginError("invalid_workspace") from None
        self.workspace_id = workspace_id
        self.operations = {operation.id.replace(".", "_"): operation for operation in definitions()
                           if (operation.agent_callable or operation.id in LEGACY)
                           and (not plugins or operation.plugin in plugins)}
        if plugins and not set(plugins) <= {operation.plugin for operation in definitions()}:
            raise PluginError("unknown_plugin")
        self.client = httpx.Client(transport=transport, follow_redirects=False, trust_env=False,
                                   timeout=30, limits=httpx.Limits(max_connections=4))

    def close(self):
        self.client.close()

    def request(self, method, path, *, headers=None, body=None, query=None, timeout=30):
        supplied = {**HEADERS, **(headers or {}), "Authorization": "Bearer " + token_read(self.token_file)}
        try:
            with self.client.stream(method, self.origin + path, headers=supplied, json=body,
                                    params=query, timeout=timeout) as response:
                data = bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_RESPONSE:
                        raise PluginError("response_limit_exceeded")
                media = response.headers.get("content-type", "").split(";", 1)[0]
                if response.status_code not in range(200, 300):
                    if response.status_code == 409 and media == "application/json":
                        value = json.loads(data, object_pairs_hook=pairs,
                                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                        if isinstance(value, dict) and value.get("outcome") in {
                                "not_found", "reserved", "running", "saved", "unknown", "failed", "abandoned"}:
                            return {**value, "http_status": 409, "recovery_required": True}
                    code = "sign_in_required" if response.status_code == 401 else "operation_rejected"
                    return {"error": code, "http_status": response.status_code}
                if media == "application/pdf":
                    if not data.startswith(b"%PDF-"):
                        raise PluginError("invalid_document_response")
                    return {"document": {"mime_type": media, "byte_length": len(data),
                            "sha256": hashlib.sha256(data).hexdigest(),
                            "base64": base64.b64encode(data).decode("ascii")}}
                if media != "application/json":
                    raise PluginError("unsupported_api_response")
                return json.loads(data, object_pairs_hook=pairs,
                                  parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except httpx.RequestError:
            return {"error": "response_unconfirmed", "recovery_required": True,
                    "automatic_retry": False}
        except (ValueError, UnicodeError, RecursionError):
            raise PluginError("invalid_api_response") from None

    def catalog(self):
        value = self.request("GET", "/connections/plugins", headers={"X-Cosmas-Connection-Contract": "1"})
        if not isinstance(value, dict) or "tools" not in value:
            raise PluginError(value.get("error", "catalog_unavailable") if isinstance(value, dict) else "catalog_unavailable")
        # The remote catalog controls availability, never executable paths/schema.
        try:
            if value["_meta"]["ai.cosmas/contract"] != CONTRACT or not isinstance(value["tools"], list):
                raise ValueError
            known = {operation.id for operation in definitions()}
            enabled = {}
            for row in value["tools"]:
                meta = row["_meta"][META]
                identity, available = meta["id"], meta["feature_enabled"]
                if not isinstance(identity, str) or identity in enabled or type(available) is not bool:
                    raise ValueError
                enabled[identity] = available if identity in known else False
            return enabled
        except (KeyError, ValueError, TypeError):
            raise PluginError("invalid_catalog_response") from None

    def tool_definitions(self):
        enabled = self.catalog()
        return [tool(operation, True) for operation in self.operations.values() if enabled.get(operation.id, False)]

    def call(self, name, arguments):
        operation = self.operations.get(name)
        if operation is None:
            raise PluginError("unknown_tool")
        schema = tool(operation, False)["inputSchema"]
        try:
            if (not isinstance(arguments, dict) or len(json.dumps(arguments, allow_nan=False).encode()) > 65536
                    or list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(arguments))):
                raise ValueError
        except (ValueError, TypeError, RecursionError):
            raise PluginError("invalid_tool_arguments") from None
        if (self.workspace_id is not None and "workspace_id" in arguments
                and arguments["workspace_id"] != self.workspace_id):
            raise PluginError("workspace_outside_session")
        if not self.catalog().get(operation.id, False):
            raise PluginError("capability_unavailable")
        path = operation.path
        for key in re.findall(r"\{([a-z_]+)\}", path):
            value = str(arguments[key])
            if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
                raise PluginError("invalid_path_argument")
            path = path.replace("{" + key + "}", value)
        headers = dict(operation.extra_headers)
        if operation.header:
            headers[operation.header] = "1"
        result = self.request(operation.method, path, headers=headers,
                              body=arguments["request"] if operation.method == "POST" else None,
                              query={key: arguments[key] for key, _ in operation.query_arguments},
                              timeout=operation.deadline_seconds)
        return {"operation": operation.id, "result": result, "recovery": operation.recovery}
