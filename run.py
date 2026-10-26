"""Start the data explorer on http://localhost:8000 (checks Zetaris first).

    python run.py [--port 8000] [--reload]
"""

from __future__ import annotations

import argparse
import sys

import uvicorn

from coverage_detective.data.zetaris import status as zetaris_status


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()
    state = zetaris_status()  # also catches a driver restarted without our data mount
    if state == "ok":
        print("Zetaris: reachable, data sources readable")
    else:
        print(f"Zetaris problem: {state}", file=sys.stderr)
        print("The map still works; cell details (which query Zetaris) will fail until this is fixed.", file=sys.stderr)
    uvicorn.run("coverage_detective.api.app:app", host="127.0.0.1", port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
