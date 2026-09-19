#!/bin/bash
# Robust deploy with retry and monitoring

set -e

REMOTE_USER="faizov"
REMOTE_HOST="37.75.249.204"
REMOTE_DIR="/home/faizov/projects/NEFTECODE2026"
LOCAL_DIR="/Users/falexsun/code/Нефтекод"
MAX_RETRIES=3

echo "=================================="
echo "ROBUST DEPLOY TO A100 SERVER"
echo "=================================="

# Function for retry
retry_command() {
    local cmd="$1"
    local desc="$2"
    local attempt=1

    while [ $attempt -le $MAX_RETRIES ]; do
        echo "Attempt $attempt/$MAX_RETRIES: $desc"
        if eval "$cmd"; then
            echo "✓ Success"
            return 0
        else
            echo "✗ Failed, retrying..."
            attempt=$((attempt + 1))
            sleep 5
        fi
    done

    echo "✗ Failed after $MAX_RETRIES attempts"
    return 1
}

# 1. Test connection
echo ""
echo "[1/6] Testing SSH connection..."
retry_command "ssh -o ConnectTimeout=10 ${REMOTE_USER}@${REMOTE_HOST} 'echo Connection OK'" "SSH test"

# 2. Sync code with retry
echo ""
echo "[2/6] Syncing code..."
retry_command "rsync -avz --timeout=60 --progress \
  --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' \
  --exclude='.DS_Store' --exclude='mlruns' --exclude='.venv' \
  '${LOCAL_DIR}/project/scripts/train_robust_gpu.py' \
  '${LOCAL_DIR}/eda/eda_utils.py' \
  '${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/scripts/'" \
  "Code sync"

# 3. Setup environment
echo ""
echo "[3/6] Setting up environment..."
ssh ${REMOTE_USER}@${REMOTE_HOST} << 'ENDSSH'
cd /home/faizov/projects/NEFTECODE2026

# Create dirs
mkdir -p data checkpoints logs scripts

# Setup venv
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

source venv/bin/activate

# Install packages
pip install --upgrade pip wheel setuptools
pip install numpy pandas scikit-learn 2>&1 | tail -5

# Try GPU packages
pip install catboost 2>&1 | tail -5
pip install lightgbm 2>&1 | tail -5
pip install xgboost 2>&1 | tail -5

echo "✓ Environment ready"
ENDSSH

# 4. Check GPU
echo ""
echo "[4/6] Checking GPU..."
ssh ${REMOTE_USER}@${REMOTE_HOST} << 'ENDSSH'
if command -v nvidia-smi &> /dev/null; then
    nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv
else
    echo "⚠ nvidia-smi not found, will use CPU"
fi
ENDSSH

# 5. Sync data if needed
echo ""
echo "[5/6] Checking data..."
ssh ${REMOTE_USER}@${REMOTE_HOST} "ls -lh ${REMOTE_DIR}/data/*.csv 2>/dev/null || echo 'No CSV data found'"

echo ""
echo "Note: If no data on server, will use synthetic data for testing"
read -p "Continue? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted"
    exit 1
fi

# 6. Launch training with tmux (survives disconnect)
echo ""
echo "[6/6] Launching training in tmux..."
ssh ${REMOTE_USER}@${REMOTE_HOST} << 'ENDSSH'
cd /home/faizov/projects/NEFTECODE2026

source venv/bin/activate

# Kill old tmux session if exists
tmux kill-session -t neftekod_training 2>/dev/null || true

# Start new tmux session
tmux new-session -d -s neftekod_training

# Run training in tmux
tmux send-keys -t neftekod_training "source venv/bin/activate" C-m
tmux send-keys -t neftekod_training "cd /home/faizov/projects/NEFTECODE2026" C-m
tmux send-keys -t neftekod_training "python3 scripts/train_robust_gpu.py --max-models 100 2>&1 | tee logs/training_$(date +%Y%m%d_%H%M%S).log" C-m

echo ""
echo "✓ Training started in tmux session 'neftekod_training'"
echo ""
echo "To attach: tmux attach -t neftekod_training"
echo "To detach: Ctrl+B then D"
echo "To view logs: tail -f logs/training_*.log"
ENDSSH

echo ""
echo "=================================="
echo "✓ DEPLOYMENT COMPLETE"
echo "=================================="
echo ""
echo "Training is running in tmux (survives disconnect!)"
echo ""
echo "Monitor with:"
echo "  ssh ${REMOTE_USER}@${REMOTE_HOST} 'tmux attach -t neftekod_training'"
echo ""
echo "Or tail logs:"
echo "  ssh ${REMOTE_USER}@${REMOTE_HOST} 'tail -f ${REMOTE_DIR}/logs/training_*.log'"
echo ""
echo "Or check progress remotely:"
echo "  ssh ${REMOTE_USER}@${REMOTE_HOST} 'cat ${REMOTE_DIR}/checkpoints/training_state.json'"
echo ""
echo "Estimated time: 15-30 minutes"
echo ""
echo "To fetch results later:"
echo "  scp ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/best_base_model.pkl ."
echo "  scp ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/training_results.json ."
