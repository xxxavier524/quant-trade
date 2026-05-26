"""Auto-research loop: parameter optimization + strategy tuning.
Based on Karpathy's autoresearch concept.
"""
import json
import logging
from pathlib import Path
from datetime import datetime
from itertools import product

logger = logging.getLogger(__name__)

class AutoResearch:
    def __init__(self, config_path="config/auto_research_state.json"):
        self.config_path = Path(config_path)
        self.state = self._load_state()
        self.improvement_ratio = 1.05
        self.snapshot_keep = 3

    def _load_state(self) -> dict:
        if self.config_path.exists():
            with open(self.config_path) as f: return json.load(f)
        return {"experiments": [], "best_params": {}, "snapshots": []}

    def _save_state(self):
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w") as f: json.dump(self.state, f, indent=2)

    def run_param_sweep(self, strategy: str, param_grid: dict, eval_fn, base_metric: float) -> dict:
        best_metric = base_metric
        best_params = None
        results = []
        keys = list(param_grid.keys())
        values = list(param_grid.values())
        for combo in product(*values):
            params = dict(zip(keys, combo))
            try:
                metric = eval_fn(params)
            except Exception as e:
                logger.warning(f"Experiment failed: {params} -> {e}")
                metric = None
            exp = {"strategy": strategy, "params": params, "metric": metric, "timestamp": datetime.now().isoformat()}
            results.append(exp)
            if metric is not None and metric > best_metric * self.improvement_ratio:
                best_metric = metric
                best_params = params
                logger.info(f"New best: {params} -> {metric:.4f} (was {base_metric:.4f})")
        self.state["experiments"] = (self.state["experiments"] + results)[-200:]
        if best_params:
            if strategy in self.state["best_params"]:
                self.state["snapshots"].append({"strategy": strategy, "params": self.state["best_params"][strategy],
                                                "metric": base_metric, "timestamp": datetime.now().isoformat()})
                self.state["snapshots"] = self.state["snapshots"][-self.snapshot_keep:]
            self.state["best_params"][strategy] = best_params
        self._save_state()
        return {"strategy": strategy, "best_params": best_params or self.state["best_params"].get(strategy),
                "best_metric": best_metric, "experiments_run": len(results), "improved": best_params is not None}

    def get_optimization_tasks(self) -> list:
        return [
            {"strategy": "B1B2", "param_grid": {"j_threshold": [10, 12, 13, 15, 18], "shrink_ratio": [0.2, 0.25, 0.3, 0.35], "b2_window": [3, 5, 7]}},
            {"strategy": "BRICK", "param_grid": {"brick_amplitude": [1.5, 2.0, 2.5], "vol_mult": [1.2, 1.5, 2.0], "breakout_threshold": [0.6, 0.7, 0.8]}},
            {"strategy": "NEEDLE", "param_grid": {"shadow_ratio": [2.5, 3.0, 3.5], "pullback_ratio": [0.3, 0.382, 0.5, 0.618], "j_threshold": [8, 10, 13, 15]}},
        ]
