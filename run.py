"""Start the data explorer on http://localhost:8000 (checks Zetaris first).

    python run.py [--port 8000] [--reload]
"""

from __future__ import annotations

import argparse
import sys

import uvicorn

from coverage_detective.data.zetaris import ZetarisError, query


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()
    try:
        query("SELECT 1 AS ok", timeout=10)
        print("Zetaris: reachable")
    except ZetarisError as e:
        print(f"Zetaris is not reachable: {e}", file=sys.stderr)
        print("Start it with:  scripts/zetaris/compose.sh up -d   (then ~/zetaris-platform/verify.sh)", file=sys.stderr)
        print("The map still works; cell details (which query Zetaris) will fail until it is up.", file=sys.stderr)
    uvicorn.run("coverage_detective.api.app:app", host="127.0.0.1", port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
