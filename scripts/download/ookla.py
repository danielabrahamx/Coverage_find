"""Download UK extracts of the latest Ookla mobile performance tiles (Parquet).

    python scripts/download/ookla.py [--quarters 4]

Source: public S3 bucket `ookla-open-data` over HTTPS, no account needed.
Licence: CC BY-NC-SA 4.0 (Speedtest by Ookla Global Fixed and Mobile Network Performance Maps).

Each quarter's global file is ~190 MB, sorted by quadkey. Rather than download it all,
this reads the Parquet footer with HTTP range requests, fetches only the row groups whose
quadkey range can hold UK tiles and only the columns we use (~40 MB), then keeps tiles in
the UK bounding box. Output: data/raw/ookla/<YYYYQn>_mobile_tiles_uk.parquet; existing
files are skipped.
"""

from __future__ import annotations

import argparse
import io
import math
import re
import sys
from pathlib import Path

import httpx
import pyarrow.compute as pc
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from coverage_detective.config import RAW, UK_BBOX  # noqa: E402

BUCKET = "https://ookla-open-data.s3.amazonaws.com"
PREFIX = "parquet/performance/type=mobile/"
OUT_DIR = RAW / "ookla"
COLUMNS = ["quadkey", "tile_x", "tile_y", "avg_d_kbps", "avg_u_kbps", "avg_lat_ms", "tests", "devices"]
TILE_ZOOM = 16
PREFIX_ZOOM = 6  # quadkey prefixes at this zoom cover the UK bbox (each tile ~600 km)


class HttpFile(io.RawIOBase):
    """A read-only, seekable file over HTTP range requests, for pyarrow."""

    def __init__(self, url: str, client: httpx.Client):
        self.url, self.client, self.pos = url, client, 0
        self.size = int(client.head(url).raise_for_status().headers["content-length"])
        self.fetched = 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, offset: int, whence: int = 0) -> int:
        self.pos = {0: offset, 1: self.pos + offset, 2: self.size + offset}[whence]
        return self.pos

    def read(self, n: int = -1) -> bytes:
        end = self.size if n < 0 else min(self.size, self.pos + n)
        if end <= self.pos:
            return b""
        r = self.client.get(self.url, headers={"Range": f"bytes={self.pos}-{end - 1}"})
        data = r.raise_for_status().content
        self.pos += len(data)
        self.fetched += len(data)
        return data


def list_quarters(client: httpx.Client) -> list[str]:
    """Keys of every mobile tiles file, oldest first."""
    keys, token = [], None
    while True:
        params = {"list-type": "2", "prefix": PREFIX}
        if token:
            params["continuation-token"] = token
        xml = client.get(BUCKET, params=params).raise_for_status().text
        keys += re.findall(r"<Key>([^<]+_performance_mobile_tiles\.parquet)</Key>", xml)
        token = (re.findall(r"<NextContinuationToken>([^<]+)<", xml) or [None])[0]
        if not token:
            return sorted(keys)


def quarter_label(key: str) -> str:
    """'.../year=2026/quarter=3/...' -> '2026Q3'."""
    year, quarter = re.search(r"year=(\d{4})/quarter=(\d)", key).groups()
    return f"{year}Q{quarter}"


def tile_xy(lat: float, lon: float, zoom: int) -> tuple[int, int]:
    n = 2**zoom
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n)
    return x, y


def quadkey(x: int, y: int, zoom: int) -> str:
    return "".join(str(((x >> i) & 1) | (((y >> i) & 1) << 1)) for i in range(zoom - 1, -1, -1))


def uk_quadkey_ranges() -> list[tuple[str, str]]:
    """(lowest, highest) zoom-16 quadkeys under each zoom-6 tile touching the UK bbox."""
    b = UK_BBOX
    x0, y0 = tile_xy(b["max_lat"], b["min_lon"], PREFIX_ZOOM)
    x1, y1 = tile_xy(b["min_lat"], b["max_lon"], PREFIX_ZOOM)
    pad = TILE_ZOOM - PREFIX_ZOOM
    return [
        (p + "0" * pad, p + "3" * pad)
        for p in (quadkey(x, y, PREFIX_ZOOM) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1))
    ]


def download_uk(key: str, dest: Path, client: httpx.Client) -> None:
    f = HttpFile(f"{BUCKET}/{key}", client)
    pf = pq.ParquetFile(f)
    meta = pf.metadata
    qk = meta.schema.names.index("quadkey")
    ranges = uk_quadkey_ranges()
    groups = []
    for i in range(meta.num_row_groups):
        stats = meta.row_group(i).column(qk).statistics
        if stats is None or not stats.has_min_max or any(
            stats.min <= hi and stats.max >= lo for lo, hi in ranges
        ):
            groups.append(i)
    table = pf.read_row_groups(groups, columns=COLUMNS)
    b = UK_BBOX
    keep = pc.and_(
        pc.and_(pc.greater_equal(table["tile_x"], b["min_lon"]), pc.less_equal(table["tile_x"], b["max_lon"])),
        pc.and_(pc.greater_equal(table["tile_y"], b["min_lat"]), pc.less_equal(table["tile_y"], b["max_lat"])),
    )
    table = table.filter(keep)
    tmp = dest.with_suffix(".part")
    pq.write_table(table, tmp)
    tmp.rename(dest)
    print(
        f"  {dest.name}: {table.num_rows:,} tiles from row groups {groups} of {meta.num_row_groups}; "
        f"fetched {f.fetched / 1e6:.0f} of {f.size / 1e6:.0f} MB"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--quarters", type=int, default=4, help="how many recent quarters (default 4)")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        for key in list_quarters(client)[-args.quarters:]:
            dest = OUT_DIR / f"{quarter_label(key)}_mobile_tiles_uk.parquet"
            if dest.exists():
                print(f"exists: {dest.name}")
                continue
            print(f"fetching UK tiles from {key}", flush=True)
            download_uk(key, dest, client)
    print("done")


if __name__ == "__main__":
    main()
