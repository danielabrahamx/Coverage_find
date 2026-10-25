"""Ofcom postcode-level mobile coverage API: stub.

The Ofcom API is not available to this project, so this always returns None unless
OFCOM_API_KEY is set and a real client is written. Callers must treat None as "no Ofcom
data" and not as "no coverage". Residents are pointed to Ofcom's own checker instead:
https://www.ofcom.org.uk/mobile-coverage-checker
"""

from __future__ import annotations

from coverage_detective.config import env

COVERAGE_CHECKER_URL = "https://www.ofcom.org.uk/mobile-coverage-checker"


def postcode_coverage(postcode: str) -> dict | None:
    """Predicted coverage per operator for a postcode, or None (always, for now)."""
    if not env("OFCOM_API_KEY"):
        return None
    return None  # no client yet: the key alone is not enough
