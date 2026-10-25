import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

from coverage_detective.data import manifest

ROOT = Path(__file__).resolve().parents[1]


def _load_refresh():
    spec = importlib.util.spec_from_file_location("refresh", ROOT / "scripts" / "refresh.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["refresh"] = module  # dataclasses need the module registered
    spec.loader.exec_module(module)
    return module


def test_record_and_evidence_meta(tmp_path, monkeypatch):
    monkeypatch.setattr(manifest, "MANIFEST_PATH", tmp_path / "manifest.json")
    out = tmp_path / "ookla_mobile_r7.parquet"
    pd.DataFrame({"cell_id": ["a", "b", "c"]}).to_parquet(out)
    entry = manifest.record(
        "ookla", title="t", data_period="2026Q3", downloaded={"x.parquet": "2026-10-23", "y.parquet": "2026-10-20"},
        outputs=[out], refresh="quarterly", licence="CC BY-NC-SA 4.0",
    )
    assert entry["outputs"]["ookla_mobile_r7.parquet"]["rows"] == 3
    assert len(entry["outputs"]["ookla_mobile_r7.parquet"]["sha256"]) == 64
    meta = manifest.evidence_meta("CD_OOKLA_MOBILE.ookla_mobile_r7")
    assert meta == {"source_key": "ookla", "data_period": "2026Q3", "as_of": "2026-10-23"}
    with pytest.raises(KeyError):
        manifest.evidence_meta("CD_NOPE.nope")
    assert manifest.live_meta()["data_period"] == "live"


def test_failed_download_restores_previous_file(tmp_path, monkeypatch):
    refresh = _load_refresh()
    raw = tmp_path / "234.csv.gz"
    raw.write_bytes(b"old data")

    def failing_download(*args):
        raise RuntimeError("network down")

    monkeypatch.setattr(refresh, "run", failing_download)
    with pytest.raises(RuntimeError):
        refresh.swap_and_download([raw], "scripts/download/opencellid.py")
    assert raw.read_bytes() == b"old data"
    assert not raw.with_name("234.csv.gz.prev").exists()
