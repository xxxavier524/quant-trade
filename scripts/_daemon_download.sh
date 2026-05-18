#!/bin/bash
# 下载守护进程：自动重启，直到所有股票下载完成
VENV="/Users/qiushixuan/cc/quantan trade/.venv"
SCRIPT="/Users/qiushixuan/cc/quantan trade/scripts/download_a_share_data.py"
OUTDIR="/Volumes/Mac-480g外接/quantan_data/day"

cd "/Users/qiushixuan/cc/quantan trade"
source "$VENV/bin/activate"

ATTEMPT=0
MAX_ATTEMPTS=100
while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
    ATTEMPT=$((ATTEMPT + 1))
    echo "[DAEMON] Attempt $ATTEMPT at $(date)"

    # Count existing files
    EXISTING=$(ls "$OUTDIR"/*.csv 2>/dev/null | wc -l | tr -d ' ')
    echo "[DAEMON] Existing files: $EXISTING"

    # If we have >5000 files, we're done
    if [ "$EXISTING" -gt 5000 ]; then
        echo "[DAEMON] DONE: $EXISTING files downloaded!"
        exit 0
    fi

    # Run download with progressively increasing start index
    START=$((EXISTING * 2))  # rough heuristic
    if [ $START -lt 500 ]; then START=500; fi

    python -u "$SCRIPT" \
        --start-date 2020-01-01 --end-date 2026-05-18 \
        --output-dir "$OUTDIR" \
        --start $START 2>&1

    EXIT_CODE=$?
    echo "[DAEMON] Download exited with code $EXIT_CODE at $(date)"

    # If baostock died, wait and retry
    sleep 10
done

echo "[DAEMON] Max attempts reached"
