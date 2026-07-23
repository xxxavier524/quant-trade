"""数据新鲜度统一判定单测（alphapulse.utils.data_freshness）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alphapulse.utils import data_freshness as fr  # noqa: E402


def _mk(data_dir: Path, n_fresh: int, n_stale: int, fresh="2026-07-23", stale="2026-07-21"):
    data_dir.mkdir(exist_ok=True)
    for i in range(n_fresh):
        (data_dir / f"f{i}.csv").write_text(f"date,close\n{fresh},1.0\n")
    for i in range(n_stale):
        (data_dir / f"s{i}.csv").write_text(f"date,close\n{stale},1.0\n")


def _idx(tmp_path: Path, last="2026-07-23") -> Path:
    p = tmp_path / "sh000001.csv"
    p.write_text(f"date,close\n2026-07-22,1\n{last},2\n")
    return p


def test_fresh_when_coverage_above_threshold(tmp_path, monkeypatch):
    monkeypatch.setattr(fr, "INDEX_CSV", _idx(tmp_path))
    data = tmp_path / "day"
    _mk(data, n_fresh=8, n_stale=2)              # 80% ≥ 75%
    r = fr.check_freshness(data)
    assert r["ok"] is True and r["target"] == "2026-07-23"
    assert abs(r["coverage"] - 0.8) < 1e-9


def test_stale_when_coverage_below_threshold(tmp_path, monkeypatch):
    monkeypatch.setattr(fr, "INDEX_CSV", _idx(tmp_path))
    data = tmp_path / "day"
    _mk(data, n_fresh=3, n_stale=7)              # 30% < 75%
    r = fr.check_freshness(data)
    assert r["ok"] is False and "未最新" in r["reason"]


def test_no_index_blocks(tmp_path, monkeypatch):
    monkeypatch.setattr(fr, "INDEX_CSV", tmp_path / "missing.csv")
    data = tmp_path / "day"
    _mk(data, n_fresh=10, n_stale=0)
    r = fr.check_freshness(data)
    assert r["ok"] is False and "指数基准" in r["reason"]


def test_index_latest_date(tmp_path, monkeypatch):
    monkeypatch.setattr(fr, "INDEX_CSV", _idx(tmp_path, last="2026-07-23"))
    assert fr.index_latest_date() == "2026-07-23"


def test_custom_min_coverage(tmp_path, monkeypatch):
    monkeypatch.setattr(fr, "INDEX_CSV", _idx(tmp_path))
    data = tmp_path / "day"
    _mk(data, n_fresh=6, n_stale=4)              # 60%
    assert fr.check_freshness(data, min_coverage=0.5)["ok"] is True
    assert fr.check_freshness(data, min_coverage=0.75)["ok"] is False


if __name__ == "__main__":
    import subprocess
    raise SystemExit(subprocess.call(["pytest", "-q", __file__]))
