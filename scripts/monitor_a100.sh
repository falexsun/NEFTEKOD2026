#!/bin/bash
# Monitor training progress on A100

REMOTE_USER="faizov"
REMOTE_HOST="37.75.249.204"
REMOTE_DIR="/home/faizov/projects/NEFTECODE2026"

echo "🔍 Monitoring A100 Training Progress"
echo "===================================="
echo ""

while true; do
    clear
    echo "🔍 A100 Training Monitor - $(date)"
    echo "===================================="
    echo ""

    # Check if training is running
    TRAIN_PID=$(ssh ${REMOTE_USER}@${REMOTE_HOST} "pgrep -f train_robust_gpu" 2>/dev/null)

    if [ -n "$TRAIN_PID" ]; then
        echo "✓ Training is RUNNING (PID: $TRAIN_PID)"
    else
        echo "⊗ Training process not found"
    fi

    echo ""
    echo "--- GPU Status ---"
    ssh ${REMOTE_USER}@${REMOTE_HOST} "nvidia-smi --query-gpu=utilization.gpu,utilization.memory,memory.used,temperature.gpu --format=csv,noheader" 2>/dev/null | \
        awk -F, '{printf "GPU: %s, Memory: %s, Used: %s, Temp: %s\n", $1, $2, $3, $4}'

    echo ""
    echo "--- Progress ---"

    # Check checkpoint
    CHECKPOINT=$(ssh ${REMOTE_USER}@${REMOTE_HOST} "cat ${REMOTE_DIR}/checkpoints/training_state.json 2>/dev/null" | python3 -c "import sys, json; d=json.load(sys.stdin); print(f\"Completed: {len(d.get('completed_configs', []))}/99 models\")" 2>/dev/null)

    if [ -n "$CHECKPOINT" ]; then
        echo "$CHECKPOINT"
    else
        echo "Checkpoint not yet available"
    fi

    echo ""
    echo "--- Latest Log (last 10 lines) ---"
    ssh ${REMOTE_USER}@${REMOTE_HOST} "tail -10 ${REMOTE_DIR}/logs/training_*.log 2>/dev/null" | grep -E "(Training|✓|🏆|💾)" | tail -5

    echo ""
    echo "--- Best Model So Far ---"
    ssh ${REMOTE_USER}@${REMOTE_HOST} "cat ${REMOTE_DIR}/training_results.json 2>/dev/null" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    if d.get('top_10'):
        best = d['top_10'][0]
        print(f\"Model: {best['name']}\")
        print(f\"MAE: {best['metrics']['mae']:.4f}\")
        print(f\"R²: {best['metrics']['r2']:.4f}\")
        print(f\"Time: {best['time']:.1f}s\")
    else:
        print('No results yet')
except:
    print('Results not yet available')
" 2>/dev/null || echo "Results not yet available"

    echo ""
    echo "===================================="
    echo "Updating every 10 seconds... (Ctrl+C to stop)"

    sleep 10
done
