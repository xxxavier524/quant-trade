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
