"""
Convenience launcher for the TestPilot AI Live Demo Server.

Usage (PowerShell):
    python demo_server.py
    python demo_server.py --port 8000
"""

from __future__ import annotations

import argparse
import os
import sys
import webbrowser
from pathlib import Path

# Add project root and src to sys.path
BASE_DIR = Path(__file__).resolve().parent
SRC_DIR = BASE_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from api.index import ThreadingHTTPServer, handler


def main() -> None:
    parser = argparse.ArgumentParser(description="TestPilot AI Demo Web Server")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on (default: 8000)")
    parser.add_argument("--no-browser", action="store_true", help="Do not open browser automatically")
    args = parser.parse_args()

    port = args.port
    server = ThreadingHTTPServer(("0.0.0.0", port), handler)
    url = f"http://localhost:{port}"

    print("=" * 60)
    print("  [TestPilot AI] Live Demo Application")
    print(f"  Local URL:    {url}")
    print(f"  API Health:   {url}/api/health")
    print(f"  Presets:      {url}/api/presets")
    print("=" * 60)
    print("Press Ctrl+C to stop the server.\n")

    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping TestPilot AI server. Goodbye!")
        server.server_close()


if __name__ == "__main__":
    main()
