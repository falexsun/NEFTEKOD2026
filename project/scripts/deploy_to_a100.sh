#!/bin/bash
# Deploy and run on remote A100 server

set -e

# Configuration
REMOTE_USER="faizov"
REMOTE_HOST="37.75.249.204"
REMOTE_DIR="/home/faizov/projects/NEFTECODE2026"
LOCAL_DIR="/Users/falexsun/code/Нефтекод"

echo "=================================="
echo "DEPLOY TO A100 SERVER"
echo "=================================="

# 1. Sync code to remote
echo ""
echo "[1/5] Syncing code to remote server..."
rsync -avz --progress \
  --exclude='.git' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.DS_Store' \
  --exclude='mlruns' \
  --exclude='mlartifacts' \
  --exclude='.venv' \
  "${LOCAL_DIR}/project/scripts/train_base_model_gpu.py" \
  "${LOCAL_DIR}/project/src/training/incremental_learner.py" \
  "${LOCAL_DIR}/eda/eda_utils.py" \
  "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/scripts/"

echo "✓ Code synced"

# 2. Sync data (если нужно)
echo ""
echo "[2/5] Checking data on remote..."
ssh ${REMOTE_USER}@${REMOTE_HOST} "ls -lh ${REMOTE_DIR}/data/ || echo 'Data dir not found'"

# 3. Setup environment on remote
echo ""
echo "[3/5] Setting up Python environment..."
ssh ${REMOTE_USER}@${REMOTE_HOST} << 'EOF'
cd /home/faizov/projects/NEFTECODE2026

# Create venv if not exists
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

# Activate and install dependencies
source venv/bin/activate

pip install --upgrade pip
pip install numpy pandas scikit-learn
pip install catboost lightgbm xgboost
pip install redis pickle5

echo "✓ Environment ready"
EOF

# 4. Prepare data on remote (convert to parquet for faster loading)
echo ""
echo "[4/5] Preparing data on remote..."
ssh ${REMOTE_USER}@${REMOTE_HOST} << 'EOF'
cd /home/faizov/projects/NEFTECODE2026

source venv/bin/activate

python3 << PYTHON
import sys
import pandas as pd
from pathlib import Path

data_dir = Path('data')

# Load and convert to parquet if CSV exists
if (data_dir / 'avt_tags.csv').exists():
    print("Converting AVT data to parquet...")
    avt = pd.read_csv(data_dir / 'avt_tags.csv')
    avt.to_parquet(data_dir / 'avt_tags.parquet', compression='snappy')
    print(f"✓ AVT: {avt.shape}")

if (data_dir / '242000_tags.csv').exists():
    print("Converting 24-2000 data to parquet...")
    hydro = pd.read_csv(data_dir / '242000_tags.csv')
    hydro.to_parquet(data_dir / '242000_tags.parquet', compression='snappy')
    print(f"✓ 24-2000: {hydro.shape}")

print("Data preparation complete")
PYTHON

EOF

# 5. Launch training on GPU
echo ""
echo "[5/5] Launching massive training on A100..."
echo ""
echo "Running command:"
echo "  nohup python3 scripts/train_base_model_gpu.py --max-models 200 > training.log 2>&1 &"
echo ""

ssh ${REMOTE_USER}@${REMOTE_HOST} << 'EOF'
cd /home/faizov/projects/NEFTECODE2026

source venv/bin/activate

# Check GPU
echo "GPU Status:"
nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv

# Launch training in background
nohup python3 scripts/train_base_model_gpu.py --max-models 200 > training.log 2>&1 &

TRAIN_PID=$!
echo ""
echo "✓ Training started with PID: ${TRAIN_PID}"
echo "✓ Logs: ${PWD}/training.log"
echo ""
echo "To monitor:"
echo "  ssh ${REMOTE_USER}@${REMOTE_HOST}"
echo "  tail -f /home/faizov/projects/NEFTECODE2026/training.log"
echo ""
echo "To check progress:"
echo "  ssh ${REMOTE_USER}@${REMOTE_HOST} 'ps aux | grep train_base_model'"
EOF

echo ""
echo "=================================="
echo "✓ DEPLOYMENT COMPLETE"
echo "=================================="
echo ""
echo "Next steps:"
echo "1. Monitor training: ssh ${REMOTE_USER}@${REMOTE_HOST} 'tail -f ${REMOTE_DIR}/training.log'"
echo "2. Check GPU usage: ssh ${REMOTE_USER}@${REMOTE_HOST} 'watch -n 1 nvidia-smi'"
echo "3. Fetch results when done: scp ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/best_base_model.pkl ."
