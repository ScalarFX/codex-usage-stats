"""Tiny stdlib HTTP server exposing the dashboard + JSON API."""
from __future__ import annotations

import json
import mimetypes
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import parse_qs, urlparse

from . import __version__
from .parser import parse_all
from .paths import resolve_codex_home, sessions_dir
from .stats import aggregate


def _web_root() -> Path:
    """Locate the bundled `web/` directory both in source tree and PyInstaller onefile."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        candidate = Path(base) / "web"
        if candidate.is_dir():
            return candidate
    return Path(__file__).resolve().parent.parent / "web"


def make_handler(codex_home: Path):
    web_root = _web_root()
    cache_ttl_s = 30.0
    cache_lock = Lock()
    sessions_cache: dict[str, object] = {
        "home": None,
        "signature": None,
        "sessions": [],
        "cached_at": 0.0,
    }

    def _sessions_signature(sdir: Path) -> tuple[int, int, int]:
        """Cheap change detector for rollout logs."""
        count = 0
        total_size = 0
        max_mtime_ns = 0
        if not sdir.exists():
            return (0, 0, 0)
        for p in sdir.rglob("rollout-*.jsonl"):
            try:
                st = p.stat()
            except OSError:
                continue
            count += 1
            total_size += st.st_size
            max_mtime_ns = max(max_mtime_ns, st.st_mtime_ns)
        return (count, total_size, max_mtime_ns)

    def _get_sessions(home: Path, sdir: Path, force_refresh: bool):
        now = time.monotonic()
        home_key = str(home)
        with cache_lock:
            if (
                not force_refresh
                and sessions_cache["home"] == home_key
                and sessions_cache["sessions"]
                and now - float(sessions_cache["cached_at"] or 0.0) < cache_ttl_s
            ):
                return sessions_cache["sessions"]

        signature = _sessions_signature(sdir)
        with cache_lock:
            if (
                not force_refresh
                and sessions_cache["home"] == home_key
                and sessions_cache["signature"] == signature
            ):
                return sessions_cache["sessions"]

            sessions = parse_all(sdir)
            sessions_cache["home"] = home_key
            sessions_cache["signature"] = signature
            sessions_cache["sessions"] = sessions
            sessions_cache["cached_at"] = now
            return sessions

    class Handler(BaseHTTPRequestHandler):
        server_version = f"CodexStats/{__version__}"

        def log_message(self, format, *args):  # silence default stderr spam
            return

        def _send_json(self, obj, status: int = 200):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_file(self, path: Path, status: int = 200):
            if not path.is_file():
                self.send_error(404, "not found")
                return
            ctype, _ = mimetypes.guess_type(str(path))
            body = path.read_bytes()
            self.send_response(status)
            self.send_header("Content-Type", ctype or "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            path = u.path

            if path == "/" or path == "/index.html":
                self._send_file(web_root / "index.html")
                return

            if path == "/api/config":
                self._send_json({
                    "codex_home": str(codex_home),
                    "sessions_dir": str(sessions_dir(codex_home)),
                    "sessions_dir_exists": sessions_dir(codex_home).exists(),
                    "version": __version__,
                })
                return

            if path == "/api/stats":
                q = parse_qs(u.query)
                range_ = (q.get("range", ["all"])[0] or "all").lower()
                path_override = q.get("path", [None])[0]
                force_refresh = (q.get("refresh", ["0"])[0] or "0") in {"1", "true", "yes"}
                home = resolve_codex_home(path_override) if path_override else codex_home
                sdir = sessions_dir(home)
                try:
                    sessions = _get_sessions(home, sdir, force_refresh)
                except Exception as e:  # pragma: no cover
                    self._send_json({"error": str(e)}, status=500)
                    return
                data = aggregate(sessions, range_)
                data["codex_home"] = str(home)
                data["sessions_dir"] = str(sdir)
                data["sessions_dir_exists"] = sdir.exists()
                self._send_json(data)
                return

            # static
            if path.startswith("/static/"):
                rel = path[len("/static/"):]
                target = (web_root / rel).resolve()
                try:
                    target.relative_to(web_root.resolve())
                except ValueError:
                    self.send_error(403)
                    return
                self._send_file(target)
                return

            self.send_error(404)

    return Handler


def serve(codex_home: Path, host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer((host, port), make_handler(codex_home))
    return srv
