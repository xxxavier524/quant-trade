#!/usr/bin/env bash
# 一次性追平数据 — 断档多天/换新交易日时用。
# daily_update 每轮从断点续传，本脚本循环调用直到「已最新覆盖率」达标或不再推进。
#
# 背景：全量约5200只、baostock顺序查询约3秒/只 → 单个交易日全量≈4-5小时，
# 远超日常30分钟窗口，故断档后需要手动追平一次。
#
# 用法：
#   bash scripts/catch_up_data.sh              # 默认追到覆盖率≥95%或12轮
#   COVER=0.98 ROUNDS=20 MIN=60 bash scripts/catch_up_data.sh
set -u
cd "$(dirname "$0")/.."

PY="${PY:-.venv/bin/python}"
[ -x "$PY" ] || PY="python3"
MIN="${MIN:-45}"          # 每轮 --max-minutes
ROUNDS="${ROUNDS:-12}"    # 最多轮数
COVER="${COVER:-0.95}"    # 目标覆盖率

echo "== 先补指数（硬闸门/大盘档位依赖，很快）=="
"$PY" scripts/fetch_index_data.py || echo "  指数更新失败（非致命，继续）"

prev=""
for r in $(seq 1 "$ROUNDS"); do
  echo "== 第 $r/$ROUNDS 轮增量更新（每轮≤${MIN}分钟，自动续传）=="
  "$PY" scripts/daily_update.py --max-minutes "$MIN"
  # 从自检脚本读当前覆盖率（众数日 vs 抽样）
  cov=$("$PY" scripts/check_data_health.py 2>/dev/null \
        | grep -oE '占抽样 [0-9]+/[0-9]+' | head -1 \
        | awk '{split($2,a,"/"); if(a[2]>0) printf "%.2f", a[1]/a[2]}')
  echo "   当前众数日覆盖率≈${cov:-未知}"
  # 达标退出
  awk -v c="${cov:-0}" -v t="$COVER" 'BEGIN{exit !(c+0>=t+0)}' && {
    echo "✅ 覆盖率达标（≥$COVER），追平完成。"; break; }
  # 连续两轮无推进则停（多为节假日/数据源问题，避免空转）
  [ "$cov" = "$prev" ] && { echo "⚠️ 连续两轮无推进（≈$cov），停止。检查网络/数据源。"; break; }
  prev="$cov"
done

echo "== 最终自检 =="
"$PY" scripts/check_data_health.py
