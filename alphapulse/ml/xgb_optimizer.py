"""XGBoost factor combination optimizer for short-term return prediction."""
import pandas as pd
import numpy as np
import logging
import json
from pathlib import Path
logger = logging.getLogger(__name__)

def prepare_training_data(factor_df, forward_cols, factor_cols):
    datasets = {}
    for fc in forward_cols:
        mask = factor_df[fc].notna()
        for c in factor_cols: mask = mask & factor_df[c].notna()
        if mask.sum() < 50:
            logger.warning(f"Not enough data for {fc}: {mask.sum()} samples")
            continue
        X = factor_df.loc[mask, factor_cols].values.astype(np.float32)
        y = (factor_df.loc[mask, fc] > 0).values.astype(int)
        datasets[fc] = (X, y)
    return datasets

def train_xgb_model(X, y, params=None):
    try:
        import xgboost as xgb
    except ImportError:
        logger.error("xgboost not installed. pip install xgboost")
        return None, None
    default_params = {"n_estimators": 100, "max_depth": 4, "learning_rate": 0.05,
                      "subsample": 0.8, "colsample_bytree": 0.8, "random_state": 42, "eval_metric": "logloss"}
    if params: default_params.update(params)
    model = xgb.XGBClassifier(**default_params)
    model.fit(X, y, verbose=False)
    importances = dict(zip([f"f{i}" for i in range(X.shape[1])], model.feature_importances_.tolist()))
    return model, importances

def compare_weights(linear_weights, ml_importances, factor_names):
    total = sum(ml_importances.values())
    if total == 0: return {}
    return {factor_names[int(k[1:])] if k.startswith("f") and int(k[1:]) < len(factor_names) else k: round(v/total, 4)
            for k, v in ml_importances.items()}

def optimize_factor_weights(factor_df, factor_cols, forward_col="ret_1d", output_path="config/ml_weights.json"):
    datasets = prepare_training_data(factor_df, [forward_col], factor_cols)
    if forward_col not in datasets: return {"error": f"No data for {forward_col}"}
    X, y = datasets[forward_col]
    model, importances = train_xgb_model(X, y)
    if model is None: return {"error": "XGBoost training failed"}
    ml_weights = compare_weights({}, importances, factor_cols)
    out = {"forward_col": forward_col, "ml_weights": ml_weights, "importances": importances}
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f: json.dump(out, f, indent=2)
    return out
