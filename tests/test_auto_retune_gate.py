"""auto_retune 参数替换裁决单测（P2/C6+C7，2026-07-28）。

旧实现：目标是逐信号等权指标、门槛"两指标同时+15%"、且代码写死不写参数
→ 每周固定"邻域最优，无调整建议"，自动升级从未发生。
新实现：组合级年化 + 留出窗样本外 + 三道闸（样本量/收益改善/回撤不恶化），通过则真写入。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from auto_retune import decide_update  # noqa: E402


def _r(annual, dd=-0.10, n=100):
    return {"annual_return": annual, "max_drawdown": dd, "n_taken": n}


def test_accepts_clear_out_of_sample_improvement():
    ok, why = decide_update(_r(0.12), _r(0.02))
    assert ok is True and "→" in why


def test_rejects_when_holdout_sample_too_small():
    ok, why = decide_update(_r(0.30, n=5), _r(0.02))
    assert ok is False and "样本不足" in why


def test_rejects_marginal_gain_within_noise():
    ok, why = decide_update(_r(0.035), _r(0.02))   # 仅+1.5pp < 2pp 门槛
    assert ok is False and "未达门槛" in why


def test_rejects_when_drawdown_badly_worsens():
    """收益提升但回撤相对大幅恶化 → 否决（不拿风险换收益）。

    注意回撤取 -0.30：在绝对上限(35%)之内，才能验证到"相对恶化"这道闸；
    超过绝对上限会先被前一道闸拦下（另有用例覆盖）。
    """
    ok, why = decide_update(_r(0.20, dd=-0.30), _r(0.02, dd=-0.10))
    assert ok is False and "回撤恶化" in why


def test_allows_small_drawdown_worsening_with_big_gain():
    ok, _ = decide_update(_r(0.20, dd=-0.13), _r(0.02, dd=-0.10))
    assert ok is True


def test_rejects_worse_returns():
    ok, _ = decide_update(_r(-0.05), _r(0.02))
    assert ok is False


# ---- 绝对可行性下限（2026-07-28 实测发现：只做相对比较会把"-70%→-47%"当升级）----

def test_rejects_improvement_that_is_still_losing_money():
    """核心闸门：候选自身必须赚钱。从灾难改善到亏损不是升级，不得写进生产参数。"""
    ok, why = decide_update(_r(-0.4669, dd=-0.289, n=66), _r(-0.6964, dd=-0.442, n=74))
    assert ok is False and "本身不赚钱" in why


def test_rejects_profitable_but_excessive_drawdown():
    ok, why = decide_update(_r(0.15, dd=-0.55), _r(0.02, dd=-0.10))
    assert ok is False and "回撤" in why


def test_accepts_profitable_with_acceptable_drawdown():
    ok, _ = decide_update(_r(0.14, dd=-0.20, n=80), _r(0.02, dd=-0.18, n=80))
    assert ok is True


if __name__ == "__main__":
    import subprocess
    raise SystemExit(subprocess.call(["pytest", "-q", __file__]))
