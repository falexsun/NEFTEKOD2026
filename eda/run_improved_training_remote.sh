#!/bin/bash
# Remote training script for improved Q21 multihorizon models
# Run this on the GPU server

set -e

REMOTE_HOST="faizov@37.75.249.204"
REMOTE_ROOT="/home/faizov/projects/NEFTECODE2026"
RUN_ID="q21_improved_h36_$(date +%Y%m%d_%H%M)"

echo "=========================================="
echo "Q21 Improved Training for h=3,6"
echo "Run ID: $RUN_ID"
echo "=========================================="

# Upload training script
echo "Uploading training script..."
scp eda/train_q21_multihorizon_improved.py ${REMOTE_HOST}:${REMOTE_ROOT}/eda/

# Run training on GPU
echo "Starting training on GPU server..."
ssh ${REMOTE_HOST} << EOF
cd ${REMOTE_ROOT}
source venv/bin/activate

# Check GPU
nvidia-smi

# Run training
nohup venv/bin/python eda/train_q21_multihorizon_improved.py \\
  --root ${REMOTE_ROOT} \\
  --horizons 3 6 \\
  --run-id ${RUN_ID} \\
  --gpu \\
  > eda/experiments/${RUN_ID}/training.log 2>&1 &

echo "Training started in background. PID: \$!"
echo "Monitor with: tail -f eda/experiments/${RUN_ID}/training.log"
EOF

echo ""
echo "Training launched successfully!"
echo "Monitor progress:"
echo "  ssh ${REMOTE_HOST}"
echo "  cd ${REMOTE_ROOT}"
echo "  tail -f eda/experiments/${RUN_ID}/training.log"
