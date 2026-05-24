"""NLP因子转换器 —— 将中文描述转换为量化因子代码。

支持的规则（正则匹配中文）：
- 均线交叉/上穿/下穿/金叉/死叉
- KDJ J值条件
- MACD DIF/DEA条件
- 成交量放量/缩量
- 价格涨幅/跌幅/振幅
- K线形态（阳线/阴线/上影线/下影线）
- 逻辑组合（AND/OR）
"""

import re
import json
from typing import Optional


def _make_factor_name(description: str) -> str:
    """从描述中生成简短的因子名。"""
    name = description.strip()[:20]
    name = re.sub(r'[^\w\u4e00-\u9fff]', '_', name)
    name = re.sub(r'_+', '_', name).strip('_')
    return f"NLP_{name[:20]}"


def _extract_number(text: str) -> Optional[float]:
    """从文本中提取数字。"""
    m = re.search(r'(\d+\.?\d*)', text)
    return float(m.group(1)) if m else None


def parse_description(description: str) -> dict:
    """将中文描述解析为因子条件和代码。

    Args:
        description: 中文描述，如 "5日均线上穿10日均线且成交量大于2倍60日均量"

    Returns:
        dict: {conditions, code, name, description}
    """
    conditions = []
    text = description.strip()

    # ── 振幅条件 ──
    amplitude_matches = re.findall(
        r'振幅\s*(小于|大于|小于等于|大于等于|[<>]=?)\s*(\d+\.?\d*)\s*%?',
        text
    )
    for op_str, val_str in amplitude_matches:
        val = float(val_str)
        op_map = {'小于': '<', '大于': '>', '小于等于': '<=', '大于等于': '>=',
                  '<': '<', '>': '>', '<=': '<=', '>=': '>='}
        op = op_map.get(op_str, '<')
        cond_name = f"振幅{op}{val}%"
        conditions.append({
            "type": "amplitude",
            "name": cond_name,
            "params": {"op": op, "value": val},
        })
        text = text.replace(f'振幅{op_str}{val_str}%', '').replace(f'振幅{op_str}{val_str}', '')

    # ── 均线交叉/关系 ──
    # 模式: MA5上穿MA10, 5日均线上穿10日均线, MA5大于MA10
    ma_patterns = [
        # 上穿/下穿/金叉/死叉
        r'(?:MA|ma)?(\d{1,3})(?:日)?(?:均线|MA|ma)?\s*(上穿|下穿|金叉|死叉)\s*(?:MA|ma)?(\d{1,3})(?:日)?(?:均线|MA|ma)?',
        # 大于/小于
        r'(?:MA|ma)?(\d{1,3})(?:日)?(?:均线|MA|ma)?\s*(大于|大于等于|小于|小于等于|[><]=?)\s*(?:MA|ma)?(\d{3,4})?(?:日)?(?:倍)?(?:均线|均量|MA|ma)?(\d{1,3})?',
    ]

    for pattern in ma_patterns:
        for m in re.finditer(pattern, text):
            groups = m.groups()
            p1 = int(groups[0])
            op_raw = groups[1]
            # Try to get second period
            if len(groups) >= 3 and groups[2]:
                p2 = int(groups[2])
            else:
                # Check groups[3] for the pattern with 4 groups
                p2 = int(groups[3]) if len(groups) > 3 and groups[3] else None

            if p2 is None:
                continue

            op_map = {
                '上穿': 'cross_above', '下穿': 'cross_below',
                '金叉': 'cross_above', '死叉': 'cross_below',
                '大于': '>', '大于等于': '>=', '小于': '<', '小于等于': '<=',
                '>': '>', '>=': '>=', '<': '<', '<=': '<=',
            }
            op = op_map.get(op_raw, '>')
            cond_name = f"MA{p1}{op_raw}MA{p2}"

            # Check if this is volume-related (mean of volume, not price)
            # Only treat as volume MA if the match itself explicitly mentions 均量/量
            is_volume = ('均量' in m.group(0)) and ('均线' not in m.group(0))

            conditions.append({
                "type": "ma_rel",
                "name": cond_name,
                "params": {"ma1": p1, "ma2": p2, "op": op, "is_volume": is_volume},
            })

    # ── KDJ J值 ──
    kdj_matches = re.findall(
        r'(?:KDJ的?)?J\s*(?:值)?\s*(小于|低于|大于|小于等于|大于等于|[<>]=?)\s*(\d+\.?\d*)',
        text
    )
    for op_str, val_str in kdj_matches:
        val = float(val_str)
        op_map = {'小于': '<', '低于': '<', '大于': '>', '小于等于': '<=', '大于等于': '>=',
                  '<': '<', '>': '>', '<=': '<=', '>=': '>='}
        op = op_map.get(op_str, '<')
        conditions.append({
            "type": "kdj_j",
            "name": f"KDJ_J{op}{val}",
            "params": {"op": op, "value": val},
        })

    # ── MACD DIF/DEA ──
    macd_matches = re.findall(
        r'MACD的?(?:的?)?(DIF|DEA)\s*(上穿|下穿|大于|小于|[><]=?)\s*(-?\d*\.?\d*)',
        text
    )
    for line_name, op_str, val_str in macd_matches:
        val = float(val_str) if val_str else 0
        op_map = {'上穿': 'cross_above', '下穿': 'cross_below',
                  '大于': '>', '小于': '<', '<': '<', '>': '>'}
        op = op_map.get(op_str, '>')
        conditions.append({
            "type": "macd",
            "name": f"MACD_{line_name}{op_str}{val}",
            "params": {"line": line_name, "op": op, "value": val},
        })

    # Skip DIF/DEA交叉（如DIF上穿DEA）
    macd_cross = re.findall(
        r'MACD的?(?:的?)?(DIF|DEA)\s*(上穿|下穿|金叉|死叉)\s*(DIF|DEA)',
        text
    )
    for line1, op_str, line2 in macd_cross:
        conditions.append({
            "type": "macd_cross",
            "name": f"MACD_{line1}{op_str}{line2}",
            "params": {"line1": line1, "line2": line2, "op": "cross_above" if op_str in ('上穿', '金叉') else "cross_below"},
        })

    # ── 成交量放量 ──
    vol_expand_matches = re.findall(
        r'(?:成交量|量|放量)\s*(大于|大于等于|[>≥])\s*(?:(\d+\.?\d*)\s*倍?\s*)?(?:(\d+)(?:日)?(?:均量|MA|均线))?',
        text
    )
    # Simpler patterns
    vol_expand_simple = re.findall(
        r'(?:成交量|放量)\s*(?:大于|大于等于|[>≥])\s*(\d+\.?\d*)\s*倍?\s*(?:(\d+)(?:日)?(?:均量|MA|均价))?',
        text
    )
    for mult_str, ma_period_str in vol_expand_simple:
        mult = float(mult_str)
        ma_period = int(ma_period_str) if ma_period_str else 20
        conditions.append({
            "type": "vol_expand",
            "name": f"成交量>{mult}xMA{ma_period}",
            "params": {"mult": mult, "ma_period": ma_period},
        })

    # 成交量大于N倍60日均量 (更准确的模式)
    vol_ma_pattern = re.findall(
        r'(?:成交量|量)\s*(?:大于|大于等于|≥|>)\s*(\d+\.?\d*)\s*倍\s*(?:(\d+)(?:日)?(?:均量|MA))',
        text
    )
    for mult_str, ma_period_str in vol_ma_pattern:
        mult = float(mult_str)
        ma_period = int(ma_period_str)
        # Check if we already captured it
        if not any(c.get('type') == 'vol_expand' and c['params'].get('ma_period') == ma_period for c in conditions):
            conditions.append({
                "type": "vol_expand",
                "name": f"成交量>{mult}xMA{ma_period}",
                "params": {"mult": mult, "ma_period": ma_period},
            })

    # 放量but without倍 (just "放量")
    if re.search(r'放量', text) and not conditions:
        # Default: volume > 1.5x 20-day MA vol
        if not any(c.get('type') == 'vol_expand' for c in conditions):
            conditions.append({
                "type": "vol_expand",
                "name": "放量>1.5xMA20",
                "params": {"mult": 1.5, "ma_period": 20},
            })

    # ── 成交量缩量 ──
    vol_shrink_matches = re.findall(
        r'(?:成交量|量|缩量)\s*(小于|小于等于|[<≤])\s*(?:(\d+\.?\d*)\s*倍?\s*)?(?:(\d+)(?:日)?(?:均量|MA))?',
        text
    )
    vol_shrink_simple = re.findall(
        r'(?:缩量|成交量\s*(?:小于|小于等于|[<≤]))',
        text
    )
    if vol_shrink_simple or ('缩量' in text):
        # Check if we have params
        ratio = 0.5  # default
        ma_period = 20
        for m in re.finditer(r'缩量至?(?:前日)?(\d+\.?\d*)\s*倍?', text):
            ratio = float(m.group(1))
        conditions.append({
            "type": "vol_shrink",
            "name": f"缩量<{ratio}xMA{ma_period}",
            "params": {"ratio": ratio, "ma_period": ma_period},
        })

    # ── 涨幅 ──
    up_matches = re.findall(
        r'涨幅\s*(大于|大于等于|小于|小于等于|[><]=?)\s*(\d+\.?\d*)\s*%?',
        text
    )
    for op_str, val_str in up_matches:
        val = float(val_str)
        op_map = {'大于': '>', '大于等于': '>=', '小于': '<', '小于等于': '<=',
                  '<': '<', '>': '>', '<=': '<=', '>=': '>='}
        op = op_map.get(op_str, '>')
        conditions.append({
            "type": "pct_change",
            "name": f"涨幅{op}{val}%",
            "params": {"op": op, "value": val},
        })

    # ── 跌幅 ──
    down_matches = re.findall(
        r'(?:跌|跌幅)\s*(?:幅)?\s*(大于|大于等于|小于|小于等于|[><]=?)?\s*(\d+\.?\d*)\s*%?',
        text
    )
    for op_str, val_str in down_matches:
        val = float(val_str)
        op_raw = op_str if op_str else '>'
        op_map = {'大于': '>', '大于等于': '>=', '小于': '<', '小于等于': '<=',
                  '<': '<', '>': '>', '<=': '<=', '>=': '>='}
        op = op_map.get(op_raw, '>')
        conditions.append({
            "type": "pct_change",
            "name": f"跌幅{op}{val}%",
            "params": {"op": op, "value": -val},
        })

    # ── K线形态 ──
    # 阳线
    if re.search(r'阳线', text):
        conditions.append({
            "type": "kline",
            "name": "阳线",
            "params": {"pattern": "bullish"},
        })
    # 阴线
    if re.search(r'阴线', text):
        conditions.append({
            "type": "kline",
            "name": "阴线",
            "params": {"pattern": "bearish"},
        })
    # 上影线
    shadow_up = re.findall(
        r'上影线\s*(?:长度|比例)?\s*(大于|小于)?\s*(?:实体)?\s*(\d+\.?\d*)\s*倍?',
        text
    )
    for op_str, val_str in shadow_up:
        val = float(val_str)
        op_map = {'大于': '>', '小于': '<'}
        op = op_map.get(op_str, '>') if op_str else '>'
        conditions.append({
            "type": "kline",
            "name": f"上影线{op}{val}x",
            "params": {"pattern": "upper_shadow", "op": op, "mult": val},
        })
    if re.search(r'上影线', text) and not shadow_up:
        conditions.append({
            "type": "kline",
            "name": "上影线",
            "params": {"pattern": "upper_shadow"},
        })

    # 下影线
    shadow_down = re.findall(
        r'下影线\s*(?:长度|比例)?\s*(大于|小于)?\s*(?:实体)?\s*(\d+\.?\d*)\s*倍?',
        text
    )
    for op_str, val_str in shadow_down:
        val = float(val_str)
        op_map = {'大于': '>', '小于': '<'}
        op = op_map.get(op_str, '>') if op_str else '>'
        conditions.append({
            "type": "kline",
            "name": f"下影线{op}{val}x",
            "params": {"pattern": "lower_shadow", "op": op, "mult": val},
        })
    if re.search(r'下影线', text) and not shadow_down:
        conditions.append({
            "type": "kline",
            "name": "下影线",
            "params": {"pattern": "lower_shadow"},
        })

    # ── 确定连接逻辑 ──
    is_or = bool(re.search(r'(或|或者|OR|\|\|)', text, re.IGNORECASE))
    connector = "|" if is_or else "&"

    # ── 生成代码 ──
    code = _generate_code(conditions, connector, description)

    return {
        "conditions": conditions,
        "connector": connector,
        "code": code,
        "name": _make_factor_name(description),
        "description": description,
    }


def _generate_code(conditions: list, connector: str, description: str) -> str:
    """生成因子compute函数代码。"""
    lines = []
    lines.append("import pandas as pd")
    lines.append("import numpy as np")
    lines.append("")
    lines.append("")
    lines.append("def compute(data, **params):")
    lines.append(f'    """{description}"""')
    lines.append("    close = data['close']")
    lines.append("    open_ = data['open']")
    lines.append("    high = data['high']")
    lines.append("    low = data['low']")
    lines.append("    volume = data['volume']")
    lines.append("")

    parts = []

    for i, cond in enumerate(conditions):
        ctype = cond["type"]
        params = cond["params"]

        if ctype == "ma_rel":
            p1 = params["ma1"]
            p2 = params["ma2"]
            op = params["op"]
            is_vol = params.get("is_volume", False)

            if is_vol:
                lines.append(f"    ma{p1} = volume.rolling({p1}).mean()")
                lines.append(f"    ma{p2} = volume.rolling({p2}).mean()")
            else:
                lines.append(f"    ma{p1} = close.rolling({p1}).mean()")
                lines.append(f"    ma{p2} = close.rolling({p2}).mean()")

            if op == "cross_above":
                lines.append(f"    cross_{p1}_{p2} = (ma{p1} > ma{p2}) & (ma{p1}.shift(1) <= ma{p2}.shift(1))")
                parts.append(f"cross_{p1}_{p2}")
            elif op == "cross_below":
                lines.append(f"    cross_{p1}_{p2} = (ma{p1} < ma{p2}) & (ma{p1}.shift(1) >= ma{p2}.shift(1))")
                parts.append(f"cross_{p1}_{p2}")
            else:
                parts.append(f"(ma{p1} {op} ma{p2})")

        elif ctype == "kdj_j":
            val = params["value"]
            op = params["op"]
            lines.append("    # KDJ J值计算")
            lines.append("    low_9 = low.rolling(9).min()")
            lines.append("    high_9 = high.rolling(9).max()")
            lines.append("    rsv = (close - low_9) / (high_9 - low_9 + 1e-10) * 100")
            lines.append("    k = rsv.ewm(alpha=1/3, adjust=False).mean()")
            lines.append("    d = k.ewm(alpha=1/3, adjust=False).mean()")
            lines.append("    j = 3 * k - 2 * d")
            parts.append(f"(j {op} {val})")

        elif ctype == "macd":
            line_name = params["line"]
            val = params["value"]
            op = params["op"]
            lines.append("    # MACD计算")
            lines.append("    ema12 = close.ewm(span=12, adjust=False).mean()")
            lines.append("    ema26 = close.ewm(span=26, adjust=False).mean()")
            lines.append("    dif = ema12 - ema26")
            lines.append("    dea = dif.ewm(span=9, adjust=False).mean()")
            if op in ("cross_above", "cross_below"):
                if op == "cross_above":
                    lines.append(f"    macd_cond = ({line_name.lower()} > {val}) & ({line_name.lower()}.shift(1) <= {val})")
                else:
                    lines.append(f"    macd_cond = ({line_name.lower()} < {val}) & ({line_name.lower()}.shift(1) >= {val})")
                parts.append("macd_cond")
            else:
                parts.append(f"({line_name.lower()} {op} {val})")

        elif ctype == "macd_cross":
            line1 = params["line1"]
            line2 = params["line2"]
            op = params["op"]
            lines.append("    # MACD计算")
            lines.append("    ema12 = close.ewm(span=12, adjust=False).mean()")
            lines.append("    ema26 = close.ewm(span=26, adjust=False).mean()")
            lines.append("    dif = ema12 - ema26")
            lines.append("    dea = dif.ewm(span=9, adjust=False).mean()")
            if op == "cross_above":
                lines.append(f"    macd_cross = ({line1.lower()} > {line2.lower()}) & ({line1.lower()}.shift(1) <= {line2.lower()}.shift(1))")
            else:
                lines.append(f"    macd_cross = ({line1.lower()} < {line2.lower()}) & ({line1.lower()}.shift(1) >= {line2.lower()}.shift(1))")
            parts.append("macd_cross")

        elif ctype == "vol_expand":
            mult = params["mult"]
            ma_period = params["ma_period"]
            lines.append(f"    vol_ma{ma_period} = volume.rolling({ma_period}).mean()")
            parts.append(f"(volume > vol_ma{ma_period} * {mult})")

        elif ctype == "vol_shrink":
            ratio = params["ratio"]
            ma_period = params.get("ma_period", 20)
            lines.append(f"    vol_ma{ma_period} = volume.rolling({ma_period}).mean()")
            parts.append(f"(volume < vol_ma{ma_period} * {ratio})")

        elif ctype == "pct_change":
            val = params["value"]
            op = params["op"]
            lines.append("    pct_chg = (close - close.shift(1)) / close.shift(1) * 100")
            parts.append(f"(pct_chg {op} {val})")

        elif ctype == "amplitude":
            val = params["value"]
            op = params["op"]
            lines.append("    amp = (high - low) / close.shift(1) * 100")
            parts.append(f"(amp {op} {val})")

        elif ctype == "kline":
            pattern = params["pattern"]
            if pattern == "bullish":
                parts.append("(close > open_)")
            elif pattern == "bearish":
                parts.append("(close < open_)")
            elif pattern == "upper_shadow":
                mult = params.get("mult", 2.0)
                op = params.get("op", ">")
                body = "abs(close - open_)"
                lines.append(f"    upper_shadow = high - close.clip(lower=open_)")
                lines.append(f"    body_len = abs(close - open_)")
                if op == ">":
                    parts.append(f"(upper_shadow > body_len * {mult})")
                else:
                    parts.append(f"(upper_shadow < body_len * {mult})")
            elif pattern == "lower_shadow":
                mult = params.get("mult", 2.0)
                op = params.get("op", ">")
                lines.append(f"    lower_shadow = close.clip(upper=open_) - low")
                lines.append(f"    body_len = abs(close - open_)")
                if op == ">":
                    parts.append(f"(lower_shadow > body_len * {mult})")
                else:
                    parts.append(f"(lower_shadow < body_len * {mult})")

    if not parts:
        # No conditions matched - return a simple placeholder
        lines.append("    # 未提取到具体条件，返回空")
        lines.append("    return pd.Series(False, index=data.index, name='signal')")
    else:
        joiner = f" {connector} "
        combined = joiner.join(parts)
        lines.append(f"    result = {combined}")
        lines.append("    return result.fillna(False)")

    return "\n".join(lines)


if __name__ == "__main__":
    # 测试
    tests = [
        "5日均线上穿10日均线且成交量大于2倍60日均量",
        "J值小于13且MACD的DIF大于0且涨幅大于3%",
        "阳线且成交量大于1.5倍20日均量且涨幅大于5%",
        "5日均线上穿10日均线或成交量大于2倍60日均量",
        "KDJ的J值低于20且缩量",
        "上影线大于实体2倍且阴线",
        "跌幅大于5%且振幅小于9%",
    ]
    for t in tests:
        print(f"\n{'='*60}")
        print(f"输入: {t}")
        result = parse_description(t)
        print(f"因子名: {result['name']}")
        print(f"条件数: {len(result['conditions'])}")
        print(f"连接符: {result['connector']}")
        print(f"代码:\n{result['code']}")
