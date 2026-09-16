#!/bin/bash
# Деплой и запуск расширенного обучения на A100

set -e

SERVER="a100-server"  # Замените на реальный адрес
REMOTE_DIR="/workspace/neftekod"

echo "=========================================="
echo "ДЕПЛОЙ РАСШИРЕННОГО ОБУЧЕНИЯ НА A100"
echo "=========================================="

# 1. Создать директории
echo "[1/5] Создание директорий..."
ssh $SERVER "mkdir -p $REMOTE_DIR/{data,scripts,models}"

# 2. Копировать данные
echo "[2/5] Копирование данных..."
scp ../data/avt_tags.csv $SERVER:$REMOTE_DIR/data/
scp ../data/242000_tags.csv $SERVER:$REMOTE_DIR/data/

# 3. Копировать скрипты
echo "[3/5] Копирование скриптов..."
scp train_advanced_gpu.py $SERVER:$REMOTE_DIR/scripts/
scp ../eda/eda_utils.py $SERVER:$REMOTE_DIR/scripts/

# 4. Запуск обучения
echo "[4/5] Запуск обучения на A100..."
ssh $SERVER "cd $REMOTE_DIR/scripts && nohup python3 train_advanced_gpu.py > advanced_training.log 2>&1 &"

# 5. Мониторинг
echo "[5/5] Мониторинг..."
echo ""
echo "Обучение запущено в фоне на A100!"
echo ""
echo "Для просмотра прогресса:"
echo "  ssh $SERVER 'tail -f $REMOTE_DIR/scripts/advanced_training.log'"
echo ""
echo "Для получения результатов:"
echo "  scp $SERVER:$REMOTE_DIR/scripts/advanced_training_results.json ."
echo "  scp $SERVER:$REMOTE_DIR/models/best_advanced_model_a100.pkl ../models/"
echo "  scp $SERVER:$REMOTE_DIR/models/ensemble_model_a100.pkl ../models/"
echo ""
echo "=========================================="
