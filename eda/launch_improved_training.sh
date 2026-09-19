#!/bin/bash
# Self-contained launcher for improved Q21 training

set -e

LOCAL_SCRIPT="/Users/falexsun/code/Нефтекод/eda/train_q21_multihorizon_improved.py"
REMOTE_HOST="faizov@37.75.249.204"
REMOTE_ROOT="/home/faizov/projects/NEFTECODE2026"
RUN_ID="q21_improved_h36_$(date +%Y%m%d_%H%M)"

echo "==================================="
echo "Q21 Improved Training Launcher"
echo "Run ID: $RUN_ID"
echo "==================================="

# Step 1: Upload script
echo ""
echo "[1/3] Uploading training script..."
scp "$LOCAL_SCRIPT" "${REMOTE_HOST}:${REMOTE_ROOT}/eda/" || {
    echo "ERROR: Failed to upload script"
    exit 1
}
echo "✓ Script uploaded"

# Step 2: Start training
echo ""
echo "[2/3] Starting training on GPU..."
ssh "$REMOTE_HOST" bash -s <<'REMOTE_SCRIPT'
cd /home/faizov/projects/NEFTECODE2026
source venv/bin/activate

# Check GPU
echo "GPU Status:"
nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv,noheader

# Create experiment dir
RUN_ID="q21_improved_h36_$(date +%Y%m%d_%H%M)"
mkdir -p "eda/experiments/$RUN_ID"

# Launch training
echo ""
echo "Launching training..."
nohup venv/bin/python eda/train_q21_multihorizon_improved.py \
  --root /home/faizov/projects/NEFTECODE2026 \
  --horizons 3 6 \
  --run-id "$RUN_ID" \
  --gpu \
  > "eda/experiments/$RUN_ID/training.log" 2>&1 &

PID=$!
echo "✓ Training started with PID: $PID"
echo "✓ Log file: eda/experiments/$RUN_ID/training.log"
echo ""
echo "Monitor with:"
echo "  tail -f eda/experiments/$RUN_ID/training.log"
REMOTE_SCRIPT

echo ""
echo "[3/3] Training launched!"
echo ""
echo "Next steps:"
echo "1. Monitor progress:"
echo "   ssh $REMOTE_HOST"
echo "   tail -f /home/faizov/projects/NEFTECODE2026/eda/experiments/*/training.log"
echo ""
echo "2. After completion, download results:"
echo "   scp -r ${REMOTE_HOST}:${REMOTE_ROOT}/eda/experiments/q21_improved_h36_* eda/experiments/"
