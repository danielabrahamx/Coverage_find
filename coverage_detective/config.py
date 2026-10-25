"""Paths and settings shared by every script and module."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
SAMPLES = ROOT / "data" / "samples"

H3_RES = 7

BOUNDARY_PATH = RAW / "boundary" / "uk_countries.geojson"
POPULATION_PATH = RAW / "population" / "population.tif"
CELLS_PATH = PROCESSED / "cells_r7.parquet"

# UK bounding box (lon/lat), a little generous: Shetland to Scilly, NI to Lowestoft.
UK_BBOX = {"min_lon": -8.7, "min_lat": 49.8, "max_lon": 1.9, "max_lat": 60.9}

load_dotenv(ROOT / ".env")


def env(name: str, default: str | None = None) -> str | None:
    """A setting from the environment or .env; empty strings count as unset."""
    value = os.environ.get(name, "").strip()
    return value or default


def sample_mode() -> bool:
    return (env("SAMPLE_MODE", "false") or "").lower() in ("1", "true", "yes")
