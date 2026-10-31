"""Bounded authenticated HTTP execution; no lab fixtures or vendor credentials."""

import base64
import hashlib
import json
import os
import re
import stat
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
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


@dataclass(frozen=True)
class AuthenticatedSession:
    """Trusted host adapter; credentials stay inside its authenticated proxy.

    request accepts httpx-style method/URL and keyword arguments and returns a
    streaming Response. current_revision returns a nonsecret identity/session
    revision, or None when signed out. Neither callback is supplied by tools.
    """

    request: Callable[..., httpx.Response]
    current_revision: Callable[[], str | None]


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
    def __init__(self, origin, token_file=None, *, workspace_id=None, plugins=(), transport=None, session=None):
        self.origin = origin_checked(origin)
        if session is not None and (token_file is not None or transport is not None):
            raise PluginError("ambiguous_authentication")
        if session is None and token_file is None:
            raise PluginError("authenticated_session_required")
        self.token_file = Path(token_file) if token_file is not None else None
        if self.token_file is not None and not self.token_file.is_absolute():
            raise PluginError("absolute_token_file_required")
        self.session = session
        self.session_revision = None
        if session is not None:
            if not isinstance(session, AuthenticatedSession) or not callable(session.request):
                raise PluginError("invalid_session_adapter")
            self.session_revision = self._current_revision()
        if workspace_id is not None:
            try:
                if str(UUID(workspace_id)) != workspace_id or UUID(workspace_id).int == 0:
                    raise ValueError
            except (ValueError, TypeError):
                raise PluginError("invalid_workspace") from None
        self.workspace_id = workspace_id
        self.plugins = tuple(plugins)
        known = {operation.plugin for operation in definitions()} | {"athena", "atlas_md", "elation"}
        if plugins and not set(plugins) <= known:
            raise PluginError("unknown_plugin")
        self.operations = {operation.id.replace(".", "_"): operation for operation in definitions()
                           if (operation.agent_callable or operation.id in LEGACY)
                           and (not plugins or operation.plugin in plugins)}
        self.client = None if session else httpx.Client(transport=transport, follow_redirects=False, trust_env=False,
                                                        timeout=30, limits=httpx.Limits(max_connections=4))

    def close(self):
        if self.client is not None:
            self.client.close()

    def _current_revision(self):
        try:
            assert self.session is not None
            revision = self.session.current_revision()
            if not isinstance(revision, str) or not revision or len(revision) > 128:
                raise ValueError
            return revision
        except Exception:
            raise PluginError("sign_in_required") from None

    def _require_current_session(self):
        if self.session is not None and self._current_revision() != self.session_revision:
            raise PluginError("session_changed")

    @contextmanager
    def _response(self, method, path, headers, body, query, timeout):
        if self.session is None:
            assert self.client is not None
            headers["Authorization"] = "Bearer " + token_read(self.token_file)
            with self.client.stream(method, self.origin + path, headers=headers, json=body,
                                    params=query, timeout=timeout) as response:
                yield response
            return
        self._require_current_session()
        try:
            response = self.session.request(method, self.origin + path, headers=headers,
                                            json=body, params=query, timeout=timeout)
        except httpx.RequestError:
            raise
        except Exception:
            # The host may have dispatched before failing. Preserve uncertainty
            # instead of encouraging another provider/model request.
            raise httpx.RequestError("session_request_unconfirmed") from None
        if not isinstance(response, httpx.Response):
            raise PluginError("invalid_session_response")
        try:
            self._require_current_session()
            yield response
            self._require_current_session()
        finally:
            response.close()

    def request(self, method, path, *, headers=None, body=None, query=None, timeout=30, closed_detail=False):
        if any(key.lower() in {"authorization", "cookie", "x-box-id", "x-actor-principal-id"}
               for key in (headers or {})):
            raise PluginError("identity_headers_forbidden")
        supplied = {"Content-Type": "application/json", **HEADERS, **(headers or {})}
        if self.session is not None:
            self._session_target(method, path, supplied, body, query, timeout)
        try:
            with self._response(method, path, supplied, body, query, timeout) as response:
                data = bytearray()
                for chunk in response.iter_bytes():
                    self._require_current_session()
                    data.extend(chunk)
                    if len(data) > MAX_RESPONSE:
                        raise PluginError("response_limit_exceeded")
                media = response.headers.get("content-type", "").split(";", 1)[0]
                if response.status_code not in range(200, 300):
                    value = None
                    if media == "application/json" and (response.status_code == 409 or closed_detail):
                        value = json.loads(data, object_pairs_hook=pairs,
                                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                    if response.status_code == 409 and isinstance(value, dict) and value.get("outcome") in {
                            "not_found", "reserved", "running", "saved", "unknown", "failed", "abandoned"}:
                        return {**value, "http_status": 409, "recovery_required": True}
                    code = "sign_in_required" if response.status_code == 401 else "operation_rejected"
                    result = {"error": code, "http_status": response.status_code}
                    # Closed product codes only. Extra fields can carry chart text and stay dropped.
                    if (closed_detail and response.status_code != 401 and isinstance(value, dict)
                            and set(value) == {"detail"} and isinstance(value.get("detail"), str)
                            and re.fullmatch(r"[a-z][a-z0-9_]{0,80}", value["detail"])):
                        result["detail"] = value["detail"]
                    return result
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
        except httpx.TimeoutException:
            self._require_current_session()
            if closed_detail:
                return {"error": "timeout", "automatic_retry": False}
            return {"error": "response_unconfirmed", "recovery_required": True,
                    "automatic_retry": False}
        except httpx.RequestError:
            self._require_current_session()
            return {"error": "response_unconfirmed", "recovery_required": True,
                    "automatic_retry": False}
        except (ValueError, UnicodeError, RecursionError):
            raise PluginError("invalid_api_response") from None

    def _session_target(self, method, path, headers, body, query, timeout):
        """No arbitrary proxy access through an application-session adapter.

        An EHR read is allowed when either the Athena or Elation closed command
        accepts it. A miss on one allowlist does not reject the other.
        """
        if method == "POST" and path == "/connections/ehr/reads":
            from cosmas_os.plugins.athena import command_allowed as athena_allowed
            from cosmas_os.plugins.elation import command_allowed as elation_allowed

            expected = {"Content-Type": "application/json", **HEADERS, "X-Cosmas-Ehr-Read": "1"}
            if (headers == expected and not query and (athena_allowed(body) or elation_allowed(body))
                    and 0 < timeout <= 45):
                return
            raise PluginError("invalid_tool_arguments")
        if method == "POST" and path == "/connections/cosmaneura/read":
            from cosmas_os.plugins.athena import schedule_command_allowed

            expected = {"Content-Type": "application/json", **HEADERS, "X-Cosmas-Connection-Contract": "1"}
            if headers == expected and not query and schedule_command_allowed(body) and 0 < timeout <= 30:
                return
            raise PluginError("invalid_tool_arguments")
        if method == "GET" and path == "/connections/plugins":
            expected = {"Content-Type": "application/json", **HEADERS, "X-Cosmas-Connection-Contract": "1"}
            if headers == expected and not query and body is None and 0 < timeout <= 30:
                return
        candidate = False
        for operation in self.operations.values():
            pattern = re.sub(r"\\\{([a-z_]+)\\\}", lambda match: "(?P<" + match[1] + ">[A-Za-z0-9_-]+)",
                             re.escape(operation.path))
            matched = re.fullmatch(pattern, path)
            expected = {"Content-Type": "application/json", **HEADERS, **dict(operation.extra_headers)}
            if operation.header:
                expected[operation.header] = "1"
            if (method == operation.method and matched and headers == expected
                    and set(query or {}) == {key for key, _ in operation.query_arguments}
                    and 0 < timeout <= operation.deadline_seconds):
                arguments = {**matched.groupdict(), **(query or {})}
                if method == "POST":
                    arguments["request"] = body
                elif body is not None:
                    raise PluginError("invalid_tool_arguments")
                candidate = True
                try:
                    self._validate_arguments(operation, arguments)
                except PluginError:
                    continue  # Closed action variants may share one API route.
                if (self.workspace_id is not None and operation.path.startswith("/workspaces/{workspace_id}")
                        and path.split("/")[2] != self.workspace_id):
                    raise PluginError("workspace_outside_session")
                return
        raise PluginError("invalid_tool_arguments" if candidate else "request_outside_catalog")

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
        from cosmas_os.plugins import athena, atlas_md, elation

        enabled = self.catalog()
        rows = [tool(operation, True) for operation in self.operations.values() if enabled.get(operation.id, False)]
        if not self.plugins or "elation" in self.plugins:
            rows.extend(elation.tool_definitions())
        if not self.plugins or "atlas_md" in self.plugins:
            rows.extend(atlas_md.tool_definitions())
        if not self.plugins or "athena" in self.plugins:
            rows.extend(athena.tool_definitions())
        return rows

    def call(self, name, arguments):
        from cosmas_os.plugins import athena, atlas_md, elation

        if name in elation.NAMES:
            if self.plugins and "elation" not in self.plugins:
                raise PluginError("unknown_tool")
            return elation.call(self, name, arguments)
        if name in athena.NAMES:
            if self.plugins and "athena" not in self.plugins:
                raise PluginError("unknown_tool")
            return athena.call(self, name, arguments)
        if name in atlas_md.NAMES:
            if self.plugins and "atlas_md" not in self.plugins:
                raise PluginError("unknown_tool")
            return atlas_md.call(self, name, arguments)
        operation = self.operations.get(name)
        if operation is None:
            raise PluginError("unknown_tool")
        self._validate_arguments(operation, arguments)
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

    @staticmethod
    def _validate_arguments(operation, arguments):
        schema = tool(operation, False)["inputSchema"]
        try:
            if (not isinstance(arguments, dict) or len(json.dumps(arguments, allow_nan=False).encode()) > 65536
                    or list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(arguments))):
                raise ValueError
        except (ValueError, TypeError, RecursionError):
            raise PluginError("invalid_tool_arguments") from None
