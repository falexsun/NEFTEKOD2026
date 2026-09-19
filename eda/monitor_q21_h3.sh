#!/bin/bash
# Monitor Q21 h=3 training on remote server

echo "=== GPU Status ==="
ssh faizov@37.75.249.204 "nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total --format=csv,noheader"

echo ""
echo "=== Training Process ==="
ssh faizov@37.75.249.204 "ps aux | grep 'train_q21_h3' | grep -v grep"

echo ""
echo "=== Latest Log File ==="
LOG=$(ssh faizov@37.75.249.204 "ls -t /home/faizov/projects/NEFTECODE2026/eda/train_q21_h3_*.log 2>/dev/null | head -1")
if [ -n "$LOG" ]; then
    echo "Log: $LOG"
    echo ""
    echo "=== Last 30 lines ==="
    ssh faizov@37.75.249.204 "tail -30 $LOG"
else
    echo "No log file found yet"
fi
