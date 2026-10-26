"""Start Coverage Detective: the Meterless service (port 8100), then the web app on :8000.

    python run.py [--port 8000] [--reload] [--no-memory]

Checks Zetaris first. The Meterless service (meterless_service/, needs Node 18+ and
`npm install` there) is started as a child process and stopped with the app; if it is
already running it is reused. --no-memory skips it (agents then use the in-memory fallback).
"""

from __future__ import annotations

import argparse
import atexit
import shutil
import subprocess
import sys
import time
from pathlib import Path

import uvicorn

from coverage_detective.data.zetaris import status as zetaris_status
from coverage_detective.memory.meterless import Meterless

ROOT = Path(__file__).resolve().parent
SERVICE_DIR = ROOT / "meterless_service"
LOG = ROOT / "logs" / "meterless.log"


def start_memory() -> subprocess.Popen | None:
    client = Meterless()
    if client.health().get("status") == "ok":
        print(f"Meterless: already running at {client.base_url}")
        return None
    tsx = SERVICE_DIR / "node_modules" / ".bin" / "tsx"
    if not shutil.which("node") or not tsx.exists():
        print("Meterless: NOT started (needs Node 18+ and `cd meterless_service && npm install`); "
              "agents will use the in-memory fallback", file=sys.stderr)
        return None
    LOG.parent.mkdir(exist_ok=True)
    proc = subprocess.Popen([str(tsx), "server.ts"], cwd=SERVICE_DIR, stdout=LOG.open("a"), stderr=subprocess.STDOUT)
    atexit.register(proc.terminate)
    for _ in range(100):
        if proc.poll() is not None:
            print(f"Meterless: exited early, see {LOG}", file=sys.stderr)
            return None
        h = client.health()
        if h.get("status") == "ok":
            print(f"Meterless: running at {client.base_url} ({h['records']} memory records, {h['world_events']} world events)")
            return proc
        time.sleep(0.1)
    print(f"Meterless: no health check after 10 s, see {LOG}", file=sys.stderr)
    return proc


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--no-memory", action="store_true", help="do not start the Meterless service")
    args = parser.parse_args()
    state = zetaris_status()  # also catches a driver restarted without our data mount
    if state == "ok":
        print("Zetaris: reachable, data sources readable")
    else:
        print(f"Zetaris problem: {state}", file=sys.stderr)
        print("The map still works; cell details (which query Zetaris) will fail until this is fixed.", file=sys.stderr)
    if not args.no_memory:
        start_memory()
    uvicorn.run("coverage_detective.api.app:app", host="127.0.0.1", port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
