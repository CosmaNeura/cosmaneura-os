"""Public static beta web contract: port 8080, /healthz, SPA routes; no secrets."""

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path("/app/practice-web")


class Handler(SimpleHTTPRequestHandler):
    server_version = "CosmaBot"
    sys_version = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, *_):
        # OAuth/query parameters must not appear in static-host access logs.
        pass

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        self.send_header(
            "Permissions-Policy", "camera=(), geolocation=(), microphone=(), payment=()"
        )
        self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
        super().end_headers()

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/healthz":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
            return
        translated = Path(self.translate_path(path))
        if not translated.is_file() and "." not in path.rsplit("/", 1)[-1]:
            self.path = "/index.html"
        super().do_GET()

    def list_directory(self, _):
        self.send_error(404)


if __name__ == "__main__":
    if not (ROOT / "index.html").is_file():
        raise SystemExit("Practice web bundle is missing")
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
