from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from starlette.responses import FileResponse
from starlette.staticfiles import StaticFiles

from cosmas_os.config import Settings


def install_compact_web(app: FastAPI, config: Settings) -> None:
    config.validate_runtime_configuration()
    if config.execution_backend != "postgres_local" or not config.compact_web_root:
        raise RuntimeError("compact web requires the local proof profile")
    root = Path(config.compact_web_root).resolve(strict=True)
    if not (root / "index.html").is_file() or not (root / "assets").is_dir():
        raise RuntimeError("compiled compact web bundle missing")

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers.update(
            {
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "X-Frame-Options": "DENY",
                "Permissions-Policy": "camera=(), geolocation=(), microphone=(), payment=()",
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'",
                "Cache-Control": "no-store",
            }
        )
        return response

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(root / "index.html")

    # Only compiled public assets, no arbitrary filesystem or API fallback.
    app.mount(
        "/assets",
        StaticFiles(directory=root / "assets", follow_symlink=False),
        name="compact-assets",
    )
