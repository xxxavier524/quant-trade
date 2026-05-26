import pandas as pd
import numpy as np
import pytest
from alphapulse.ml.xgb_optimizer import prepare_training_data, compare_weights

def test_prepare_training_data():
    df = pd.DataFrame({"factor_a": np.random.randn(200), "factor_b": np.random.randn(200), "ret_1d": np.random.choice([-0.02, 0.02], 200)})
    datasets = prepare_training_data(df, ["ret_1d"], ["factor_a", "factor_b"])
    assert "ret_1d" in datasets
    X, y = datasets["ret_1d"]
    assert X.shape == (200, 2)

def test_compare_weights():
    ml_imp = {"f0": 0.6, "f1": 0.4}
    result = compare_weights({}, ml_imp, ["factor_a", "factor_b"])
    assert "factor_a" in result and abs(result["factor_a"] - 0.6) < 0.01


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
