"""Entry point: python -m codex_stats"""
from __future__ import annotations

import argparse
import sys
import threading
import webbrowser

from .paths import resolve_codex_home, sessions_dir
from .server import serve


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="codex-stats",
        description="Local usage dashboard for Codex Desktop.",
    )
    ap.add_argument("--path", help="Path to the codex home dir (default: $CODEX_HOME or ~/.codex)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=0, help="0 = pick a free port")
    ap.add_argument("--no-browser", action="store_true", help="Do not auto-open the browser")
    args = ap.parse_args(argv)

    codex_home = resolve_codex_home(args.path)
    sdir = sessions_dir(codex_home)

    print(f"codex_home   : {codex_home}")
    print(f"sessions_dir : {sdir} ({'exists' if sdir.exists() else 'missing'})")

    srv = serve(codex_home, host=args.host, port=args.port)
    host, port = srv.server_address[:2]
    url = f"http://{host}:{port}/"
    print(f"listening on : {url}")

    if not args.no_browser:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()

    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
