"""Copy-to-EHR draft export route. Flag default off; clipboard paste only."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response

from cosmas_os.application.ehr_export import (
    ExportDraft,
    ExportPackage,
    build_audit_event,
    build_export_package,
    get_profile,
    render_full_note,
    render_section,
)
from cosmas_os.application.ehr_export.draft_source import find_workspace_note, load_export_draft

# Testable draft source. Production wiring replaces this; starts empty.
_DraftLoader = Callable[[str], ExportDraft | None]


def _missing_draft(_draft_id: str) -> ExportDraft | None:
    return None


_draft_loader: _DraftLoader = _missing_draft


def configure_draft_loader(loader: _DraftLoader | None) -> None:
    """Install or clear the draft loader used by the GET route."""
    global _draft_loader
    _draft_loader = loader if loader is not None else _missing_draft


def copy_to_ehr_flags_header(configuration) -> bytes:
    """Three flags only. Never note text."""
    cfg = configuration() if callable(configuration) else configuration

    def bit(name: str) -> str:
        return "1" if bool(getattr(cfg, name, False)) else "0"

    return (
        f"{bit('copy_to_ehr_enabled')},{bit('copy_to_ehr_remote_enabled')},"
        f"{bit('copy_to_ehr_fallback_enabled')}"
    ).encode()


class CopyToEhrFlagHeaderMiddleware:
    """Publish the three flags on responses the workspace already receives."""

    def __init__(self, app, configuration):
        self.app = app
        self.configuration = configuration

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        header = copy_to_ehr_flags_header(self.configuration)

        async def send_with_flags(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                headers.append((b"x-cosmas-copy-to-ehr-flags", header))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_flags)


def install_copy_to_ehr_draft_loader(*, enabled: bool, open_session, find_note=find_workspace_note) -> None:
    """Register the workspace draft loader only when copy-to-EHR is enabled."""
    if not enabled:
        return
    finder = find_note

    def load(draft_id: str) -> ExportDraft | None:
        return load_export_draft(open_session, draft_id, find_note=finder)

    configure_draft_loader(load)


def _package_json(pkg: ExportPackage) -> dict[str, Any]:
    return {
        "profile_id": pkg.profile_id,
        "draft_id": pkg.draft_id,
        "draft_revision": pkg.draft_revision,
        "payload_hash": pkg.payload_hash,
        "sections": [
            {"key": section.key, "label": section.label, "text": section.text}
            for section in pkg.sections
        ],
        "extras": [
            {"key": section.key, "label": section.label, "text": section.text}
            for section in pkg.extras
        ],
        "created_at": pkg.created_at.isoformat().replace("+00:00", "Z"),
        "expires_at": pkg.expires_at.isoformat().replace("+00:00", "Z"),
        "review_state": pkg.review_state,
        "visit_copy_to_ehr_status": pkg.visit_copy_to_ehr_status,
        "full_note": render_full_note(pkg),
        "section_notes": {section.key: render_section(pkg, section.key) for section in pkg.sections},
    }


def router(*, configuration) -> APIRouter:
    routes = APIRouter()

    @routes.get("/api/copy-to-ehr/flags")
    def copy_to_ehr_flags(response: Response) -> dict[str, bool]:
        response.headers["Cache-Control"] = "no-store"
        cfg = configuration()
        return {
            "copy_to_ehr_enabled": bool(getattr(cfg, "copy_to_ehr_enabled", False)),
            "copy_to_ehr_remote_enabled": bool(getattr(cfg, "copy_to_ehr_remote_enabled", False)),
            "copy_to_ehr_fallback_enabled": bool(getattr(cfg, "copy_to_ehr_fallback_enabled", False)),
        }

    @routes.get("/api/copy-to-ehr/drafts/{draft_id}")
    def get_export_draft(
        draft_id: str,
        response: Response,
        profile: str = Query(default="generic"),
        revision: str | None = Query(default=None),
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        cfg = configuration()
        if not bool(getattr(cfg, "copy_to_ehr_enabled", False)):
            # Opened-but-blocked stays metadata only when callers ask later.
            build_audit_event("copy_to_ehr.blocked", profile_id=None, outcome="flag_off")
            raise HTTPException(status_code=404, detail="not found")

        try:
            get_profile(profile)
        except KeyError:
            raise HTTPException(status_code=404, detail="not found") from None

        draft = _draft_loader(draft_id)
        if draft is None:
            build_audit_event("copy_to_ehr.blocked", profile_id=None, outcome="draft_missing")
            raise HTTPException(status_code=404, detail="not found")

        if revision is not None and revision != draft.draft_revision:
            build_audit_event(
                "copy_to_ehr.blocked",
                profile_id=profile,  # type: ignore[arg-type]
                outcome="revision_mismatch",
            )
            raise HTTPException(status_code=409, detail="revision_mismatch")

        pkg = build_export_package(draft, profile)
        build_audit_event(
            "copy_to_ehr.opened",
            profile_id=pkg.profile_id,
            outcome="ok",
            detail={"draft_id": pkg.draft_id, "payload_hash": pkg.payload_hash},
        )
        return _package_json(pkg)

    return routes
