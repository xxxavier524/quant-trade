import os
import sys
import pytest

# Ensure the project root is on sys.path so imports work
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from alphapulse.ml.auto_research import AutoResearch


def test_auto_research_init(tmp_path):
    ar = AutoResearch(config_path=str(tmp_path / "test_state.json"))
    assert ar.state["experiments"] == []


def test_auto_research_param_sweep(tmp_path):
    ar = AutoResearch(config_path=str(tmp_path / "test_state.json"))
    result = ar.run_param_sweep(
        "TEST",
        {"a": [1, 2, 3], "b": [10, 20]},
        lambda p: sum(v for v in p.values() if isinstance(v, (int, float))),
        base_metric=0,
    )
    assert result["experiments_run"] == 6 and result["improved"]


def test_get_optimization_tasks(tmp_path):
    ar = AutoResearch(config_path=str(tmp_path / "test_state.json"))
    tasks = ar.get_optimization_tasks()
    assert len(tasks) == 3 and tasks[0]["strategy"] == "B1B2"
