"""Bounded inspection of EXISTING product receipts. No provider read or write.

This intentionally cannot list/read Google, observe a calendar, reconcile/send a
fax, select/review a source, prepare an appointment or approve any operation.
Credentials are supplied by an open FD. Reports contain no response material.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit
from uuid import UUID

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cosmas_os.api.fax_status_schemas import FaxStatus  # noqa: E402
from cosmas_os.api.vendor_work_schemas import public_digest  # noqa: E402
from cosmas_os.domain.hashing import payload_hash  # noqa: E402
from cosmas_os.ports.google_calendar import GoogleCalendarObservation  # noqa: E402
from cosmas_os.ports.scheduling_actions import AppointmentIntent  # noqa: E402

MAX_PLAN = 16384
MAX_WORKSPACE = 12_000_000


class Refused(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(condition, code="invalid_receipt"):
    if not condition:
        raise Refused(code)


def exact(value, keys):
    require(type(value) is dict and set(value) == set(keys), "invalid_closed_contract")


def uuid(value):
    try:
        require(type(value) is str and str(UUID(value)) == value and UUID(value).int != 0)
    except ValueError:
        raise Refused("invalid_identity") from None
    return value


def digest(value):
    require(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None, "invalid_digest")
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def pairs(values):
    result = {}
    for key, value in values:
        require(key not in result, "ambiguous_json")
        result[key] = value
    return result


def decoded(raw):
    try:
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(Refused("ambiguous_json")))
    except (ValueError, UnicodeError, RecursionError):
        raise Refused("invalid_json") from None


def plan_checked(plan):
    exact(plan, {"contract_version", "mode", "origin", "box_id", "owner_id", "workspace_id",
                 "note", "messages", "calendar", "sources", "faxes", "appointments"})
    require(type(plan["contract_version"]) is int and plan["contract_version"] == 1)
    require(plan["mode"] in {"synthetic_fixture", "saved_receipts"})
    for name in ("box_id", "owner_id", "workspace_id"):
        uuid(plan[name])
    try:
        require(type(plan["origin"]) is str and len(plan["origin"]) <= 256
                and plan["origin"].isascii() and not re.search(r"[\s\\]", plan["origin"]), "invalid_origin")
        origin = urlsplit(plan["origin"])
        require(origin.path in {"", "/"} and not origin.query and not origin.fragment
                and not origin.username and not origin.password and origin.hostname)
        require((plan["mode"] == "synthetic_fixture" and origin.scheme == "http"
                 and origin.hostname == "127.0.0.1" and origin.port is not None and origin.port > 0)
                or (plan["mode"] == "saved_receipts" and origin.scheme == "https"
                    and origin.port in {None, 443}))
    except (TypeError, ValueError):
        raise Refused("invalid_origin") from None
    exact(plan["note"], {"id", "content_hash", "source_fingerprint", "core_source_sha256", "review_sha256"})
    uuid(plan["note"]["id"])
    for key in ("content_hash", "source_fingerprint"):
        digest(plan["note"][key])
    for key in ("core_source_sha256", "review_sha256"):
        if plan["note"][key] is not None:
            digest(plan["note"][key])
    for name, limit in (("messages", 2), ("calendar", 1), ("sources", 3), ("faxes", 4), ("appointments", 2)):
        require(type(plan[name]) is list and len(plan[name]) <= limit, "selector_limit")
    for item in plan["messages"]:
        exact(item, {"read_id", "kind", "source_sha256", "content_sha256"})
        uuid(item["read_id"])
        digest(item["source_sha256"])
        require(item["kind"] in {"list", "message"}
                and (item["kind"] != "list" or item["content_sha256"] is None))
        if item["content_sha256"] is not None:
            digest(item["content_sha256"])
    for item in plan["calendar"]:
        exact(item, {"observation_id", "source_sha256"})
        uuid(item["observation_id"])
        digest(item["source_sha256"])
    for item in plan["sources"]:
        exact(item, {"entry_id", "kind", "content_sha256"})
        uuid(item["entry_id"])
        digest(item["content_sha256"])
        require(item["kind"] in {"google_message", "google_calendar"})
    for item in plan["faxes"]:
        exact(item, {"ticket_id", "provider", "operation_id", "revision_id", "payload_hash", "status_sha256"})
        require(item["provider"] in {"spruce", "srfax", "documo", "efax"})
        for key in ("ticket_id", "operation_id", "revision_id"):
            uuid(item[key])
        digest(item["payload_hash"])
        digest(item["status_sha256"])
    for item in plan["appointments"]:
        exact(item, {"ticket_id", "revision_id", "payload_hash"})
        uuid(item["ticket_id"])
        uuid(item["revision_id"])
        digest(item["payload_hash"])
    for name, key in (("messages", "read_id"), ("calendar", "observation_id"), ("sources", "entry_id"),
                      ("faxes", "ticket_id"), ("appointments", "ticket_id")):
        require(len({item[key] for item in plan[name]}) == len(plan[name]), "duplicate_selector")
    require(len({item["provider"] for item in plan["faxes"]}) == len(plan["faxes"]), "duplicate_provider")
    require(any(plan[name] for name in ("messages", "calendar", "faxes", "appointments")), "no_receipt_selected")
    return plan


def _text(value, maximum, *, header=False):
    require(type(value) is str and len(value) <= maximum)
    require(not re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", value))
    require(not header or not re.search(r"[\r\n\t]", value))


def _time(value):
    require(type(value) is str)
    try:
        parsed = datetime.fromisoformat(value)
        require(parsed.tzinfo is not None and parsed.utcoffset() is not None)
    except ValueError:
        raise Refused("invalid_time") from None


def _account(value):
    exact(value, {"label", "email"})
    _text(value["label"], 320, header=True)
    _text(value["email"], 320, header=True)


def message_receipt(value, selected):
    exact(value, {"read_id", "read_key", "kind", "observation_id", "source_sha256", "payload_sha256", "status", "message", "observation"})
    digest(value["source_sha256"])
    for key in ("read_id", "read_key", "observation_id"):
        uuid(value[key])
    digest(value["payload_sha256"])
    require((value["read_id"], value["kind"], value["source_sha256"]) ==
            (selected["read_id"], selected["kind"], selected["source_sha256"]), "receipt_binding_changed")
    if value["kind"] == "list":
        require(value["status"] == "observed" and value["message"] is None
                and value["observation_id"] == value["read_id"])
        o = value["observation"]
        exact(o, {"kind", "account", "items", "more", "observed_at"})
        require(o["kind"] == "mail" and type(o["more"]) is bool and type(o["items"]) is list and len(o["items"]) <= 25)
        _account(o["account"])
        _time(o["observed_at"])
        for item in o["items"]:
            require(type(item) is dict and set(item) in ({"id", "subject", "sender", "received_at", "is_read"},
                                {"id", "thread_id", "subject", "sender", "received_at", "is_read"}))
            item_id = item["id"]
            require(isinstance(item_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", item_id))
            _text(item["subject"], 998, header=True)
            _text(item["sender"], 320, header=True)
            _time(item["received_at"])
            if "thread_id" in item:
                thread_id = item["thread_id"]
                require(isinstance(thread_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", thread_id))
            require(type(item["is_read"]) is bool)
        require(len({i["id"] for i in o["items"]}) == len(o["items"]))
        require(sha(canonical(o)) == value["payload_sha256"], "payload_hash_changed")
        return {"kind": "google_metadata_receipt", "status": "observed", "item_count": len(o["items"]), "partial": o["more"], "commitment": value["source_sha256"]}
    m = value["message"]
    require(value["observation"] is None and value["read_id"] != value["observation_id"])
    exact(m, {"message_id", "thread_id", "history_id", "subject", "sender", "received_at", "is_read", "observed_at", "status", "content", "reason", "raw_sha256", "content_sha256"})
    for key in ("message_id", "thread_id"):
        require(type(m[key]) is str and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", m[key]))
    require(m["history_id"] is None or type(m["history_id"]) is str and re.fullmatch(r"[0-9]{1,32}", m["history_id"]))
    _text(m["subject"], 998, header=True)
    _text(m["sender"], 320, header=True)
    _time(m["received_at"])
    _time(m["observed_at"])
    digest(m["raw_sha256"])
    require(type(m["is_read"]) is bool and value["status"] == m["status"])
    if m["status"] == "complete":
        _text(m["content"], 5000)
        require(m["reason"] is None and sha(m["content"]) == m["content_sha256"] == selected["content_sha256"], "content_hash_changed")
    else:
        require(m["status"] == "needs_human" and m["content"] is None and m["content_sha256"] is None
                and selected["content_sha256"] is None and m["reason"] in {"attachment", "html_only", "unsupported_mime", "oversize", "ambiguous", "invalid_encoding"})
    # Its payload hash includes private custody. Public plaintext hash and the
    # previously recorded opaque source commitment are verifiable here.
    return {"kind": "google_message_receipt", "status": m["status"], "commitment": value["source_sha256"], "content_sha256": m["content_sha256"], "private_payload_recomputed": False}


def calendar_receipt(value, selected):
    exact(value, {"contract_version", "observation_id", "observation_key", "source_sha256", "payload_sha256", "observation"})
    require(type(value["contract_version"]) is int and value["contract_version"] == 1)
    uuid(value["observation_key"])
    require((value["observation_id"], value["source_sha256"]) == (selected["observation_id"], selected["source_sha256"]), "receipt_binding_changed")
    observation = GoogleCalendarObservation.model_validate_json(canonical(value["observation"]))
    require(sha(canonical(value["observation"])) == value["payload_sha256"], "payload_hash_changed")
    return {"kind": "google_calendar_receipt", "status": "observed", "event_count": len(observation.items),
            "partial": observation.more, "window_days": 7, "availability_established": False, "commitment": value["source_sha256"]}


def note_binding(workspace, plan):
    require(workspace["id"] == plan["workspace_id"], "workspace_scope_changed")
    note = workspace["note"]["latest"]
    if note is None:
        raise Refused("note_integrity_changed")
    require(payload_hash({"content": note["content"]}) == note["content_hash"], "note_integrity_changed")
    expected = {"id": note["id"], "content_hash": note["content_hash"], "source_fingerprint": note["source_fingerprint"],
                "core_source_sha256": sha(canonical(note["core_source"])) if note["core_source"] is not None else None,
                "review_sha256": sha(canonical(note["review"])) if note["review"] is not None else None}
    require(expected == plan["note"], "clinical_note_changed")
    for selected in plan["sources"]:
        entry = next((e for e in workspace["entries"] if e["id"] == selected["entry_id"]), None)
        if entry is None:
            raise Refused("selected_source_missing")
        require(entry["kind"] == selected["kind"], "selected_source_missing")
        state = "google_source_state" if selected["kind"] == "google_message" else "calendar_source_state"
        require(entry.get(state) == "current" and sha(entry["content"]) == selected["content_sha256"], "selected_source_unavailable")
    return sha(canonical(expected))


class SavedReceiptClient:
    def __init__(self, plan, token, *, transport=None):
        self.plan = plan_checked(plan)
        require(type(token) is str and 1 <= len(token) <= 16384 and token.isascii()
                and all(33 <= ord(c) <= 126 for c in token), "invalid_token_input")
        self.client = httpx.Client(base_url=plan["origin"].rstrip("/"), transport=transport,
            trust_env=False, follow_redirects=False, timeout=httpx.Timeout(10),
            headers={"Authorization": "Bearer " + token, "Accept": "application/json", "Accept-Encoding": "identity", "Cache-Control": "no-store",
                     "X-Cosmas-Draft-Recovery": "2", "X-Cosmas-Team-Contract": "4", "X-Cosmas-Model-Contract": "1"})
        self.requests = 0

    def close(self):
        self.client.close()

    def read(self, path, *, body=None, header=None, maximum=131072):
        # These paths are constructed exclusively from validated selectors.
        deadline = monotonic() + 15
        request = self.client.build_request("POST" if body is not None else "GET", path,
            json=body if body is not None else None, headers=header)
        request.headers.pop("Cookie", None)
        self.requests += 1
        try:
            response = self.client.send(request, stream=True, follow_redirects=False)
            try:
                require(response.status_code == 200, "http_receipt_unavailable")
                require(response.headers.get("content-type", "").split(";", 1)[0].lower() == "application/json"
                        and "no-store" in {p.strip().lower() for p in response.headers.get("cache-control", "").split(",")}
                        and response.headers.get("content-encoding", "identity") == "identity", "unsafe_response_headers")
                length = response.headers.get("content-length")
                require(length is None or length.isdigit() and int(length) <= maximum, "response_limit")
                raw = bytearray()
                for chunk in response.iter_raw():
                    require(monotonic() < deadline, "receipt_read_unconfirmed")
                    require(len(raw) + len(chunk) <= maximum, "response_limit")
                    raw.extend(chunk)
                require(monotonic() < deadline, "receipt_read_unconfirmed")
                return decoded(raw)
            finally:
                response.close()
        except Refused:
            raise
        except Exception:
            raise Refused("receipt_read_unconfirmed") from None

    def run(self):
        p = self.plan
        root = "/workspaces/" + p["workspace_id"]
        results = []
        team = self.read("/provider-team", maximum=131072)
        require(team["recovery_scope"] == payload_hash({"contract": "cosmas-private-drafts-v1",
            "box_id": p["box_id"], "owner_id": p["owner_id"]}), "signed_scope_changed")
        before = note_binding(self.read(root, maximum=MAX_WORKSPACE), p)
        for selected in p["messages"]:
            value = self.read("/connections/google/messages", body={"action": "inspect", "read_id": selected["read_id"]}, header={"X-Cosmas-Google-Messages": "1"})
            results.append(message_receipt(value, selected))
        for selected in p["calendar"]:
            value = self.read("/connections/google/calendar-summaries", body={"action": "inspect", "observation_id": selected["observation_id"]}, header={"X-Cosmas-Google-Calendar": "1"})
            results.append(calendar_receipt(value, selected))
        for selected in p["faxes"]:
            value = self.read(root + "/vendor-work/" + selected["ticket_id"] + "/status", header={"X-Cosmas-Vendor-Contract": "1"}, maximum=8192)
            checked = FaxStatus.model_validate(value)
            require(checked.scope.public() == {"box_id": p["box_id"], "owner_id": p["owner_id"], "workspace_id": p["workspace_id"]}, "fax_scope_changed")
            require((checked.ticket_id, checked.provider, checked.operation_id, checked.revision_id, checked.payload_hash, checked.sha256) ==
                    tuple(selected[k] for k in ("ticket_id", "provider", "operation_id", "revision_id", "payload_hash", "status_sha256")), "fax_binding_changed")
            require(public_digest("cosmas-fax-status.v1", {k: v for k, v in value.items() if k not in {"sha256", "observed_at"}}) == checked.sha256, "fax_hash_changed")
            results.append({"kind": "fax_saved_receipt", "provider": checked.provider, "external_outcome": checked.external_outcome,
                            "next_step": checked.next_step.code, "verification": checked.verification, "commitment": checked.sha256})
        for selected in p["appointments"]:
            value = self.read(root + "/appointments/" + selected["ticket_id"], maximum=65536)
            require((value["workspace_id"], value["owner_id"], value["ticket_id"], value["revision_id"], value["payload_hash"]) ==
                    (p["workspace_id"], p["owner_id"], selected["ticket_id"], selected["revision_id"], selected["payload_hash"]), "appointment_binding_changed")
            intent = AppointmentIntent.model_validate(value["intent"])
            require(str(intent.selection.box_id) == p["box_id"] and str(intent.selection.owner_id) == p["owner_id"]
                    and intent.approval_hash() == selected["payload_hash"], "appointment_hash_changed")
            require(value["appointment_saved"] is False and value["dispatch_started"] is False
                    and value["result"] is None, "appointment_is_not_draft")
            require(value["state"] in {"pending_approval", "approved", "rejected"}, "appointment_state_invalid")
            results.append({"kind": "appointment_saved_proposal", "state": value["state"], "action": intent.action,
                            "commitment": selected["payload_hash"], "appointment_saved": False})
        require(before == note_binding(self.read(root, maximum=MAX_WORKSPACE), p), "clinical_note_changed")
        return {"contract_version": 1, "qualification": "saved_product_receipts_only", "mode": p["mode"],
                "plan_sha256": sha(canonical(p)), "checks": results, "clinical_note_unchanged": True,
                "selected_source_count": len(p["sources"]), "product_requests": self.requests,
                "signed_human_scope_verified": True,
                "provider_read_requests": 0, "provider_write_requests": 0, "product_mutations": 0,
                "live_provider_acceptance_established": False}


def run(plan, token, *, transport=None):
    client = None
    try:
        client = SavedReceiptClient(plan, token, transport=transport)
        return client.run(), 0
    except Refused as error:
        return {"contract_version": 1, "qualification": "saved_product_receipts_only", "error": error.code,
                "product_requests": client.requests if client else 0,
                "provider_read_requests": 0, "provider_write_requests": 0, "product_mutations": 0}, 1
    except Exception:
        return {"contract_version": 1, "qualification": "saved_product_receipts_only", "error": "receipt_validation_failed",
                "provider_read_requests": 0, "provider_write_requests": 0, "product_mutations": 0}, 1
    finally:
        if client:
            client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--token-fd", type=int, required=True, help="Already-open FD. Never a token literal")
    args = parser.parse_args()
    try:
        require(args.token_fd >= 3, "invalid_token_fd")
        require(args.plan.stat().st_size <= MAX_PLAN, "plan_limit")
        with args.plan.open("rb") as stream:
            raw_plan = stream.read(MAX_PLAN + 1)
        require(len(raw_plan) <= MAX_PLAN, "plan_limit")
        plan = decoded(raw_plan)
        with os.fdopen(os.dup(args.token_fd), "rb") as stream:
            raw = stream.read(16386)
        require(len(raw) <= 16385, "token_limit")
        token = raw.decode("ascii").rstrip("\n")
        result, code = run(plan, token)
    except Exception:
        result, code = {"contract_version": 1, "error": "acceptance_input_refused"}, 1
    print(canonical(result))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
