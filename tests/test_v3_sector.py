import pytest
from alphapulse.market.sector_strength import (
    compute_sector_strength,
    get_strong_sectors,
)


def test_compute_sector_strength_empty():
    """Invalid/nonexistent sector code should return score == 0."""
    result = compute_sector_strength("BK0000", "测试板块")
    assert result["score"] == 0
    assert result["name"] == "测试板块"
    assert result["code"] == "BK0000"
    assert result["excess_return"] == 0
    assert result["trend_score"] == 0
    assert result["vol_score"] == 0


def test_compute_sector_strength_no_data():
    """Another nonexistent sector code should return score == 0."""
    result = compute_sector_strength("BK9999", "不存在板块")
    assert result["score"] == 0


def test_get_strong_sectors_returns_list():
    """get_strong_sectors must always return a list (empty if network down)."""
    result = get_strong_sectors(0.5)
    assert isinstance(result, list)
