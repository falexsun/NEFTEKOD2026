#!/bin/bash
# Быстрый деплой и запуск на A100

set -e

echo "================================================"
echo "ЗАПУСК РАСШИРЕННОГО ОБУЧЕНИЯ НА A100"
echo "================================================"
echo ""

# Укажите адрес вашего A100 сервера
SERVER="${A100_SERVER:-a100-server}"
REMOTE_DIR="/workspace/neftekod"

echo "🎯 Сервер: $SERVER"
echo "📁 Директория: $REMOTE_DIR"
echo ""

# Проверка доступности сервера
echo "🔍 Проверка подключения к A100..."
if ! ssh -o ConnectTimeout=5 $SERVER "echo OK" &>/dev/null; then
    echo "❌ Не могу подключиться к $SERVER"
    echo ""
    echo "Установите переменную окружения A100_SERVER:"
    echo "  export A100_SERVER=your-a100-address"
    echo ""
    echo "Или отредактируйте файл:"
    echo "  nano $0"
    exit 1
fi
echo "✅ Подключение OK"
echo ""

# Создание директорий
echo "[1/5] 📂 Создание директорий на сервере..."
ssh $SERVER "mkdir -p $REMOTE_DIR/{data,scripts,models}"
echo "✅ Готово"
echo ""

# Копирование данных (если нужно)
echo "[2/5] 📤 Копирование данных..."
if ssh $SERVER "[ ! -f $REMOTE_DIR/data/avt_tags.csv ]"; then
    echo "  Копируем avt_tags.csv..."
    scp ../data/avt_tags.csv $SERVER:$REMOTE_DIR/data/
    echo "  Копируем 242000_tags.csv..."
    scp ../data/242000_tags.csv $SERVER:$REMOTE_DIR/data/
    echo "✅ Данные скопированы"
else
    echo "✅ Данные уже на сервере"
fi
echo ""

# Копирование скриптов
echo "[3/5] 📤 Копирование скриптов..."
scp train_advanced_gpu.py $SERVER:$REMOTE_DIR/scripts/
scp ../eda/eda_utils.py $SERVER:$REMOTE_DIR/scripts/ 2>/dev/null || echo "  (eda_utils.py не найден, пропускаем)"
echo "✅ Скрипты скопированы"
echo ""

# Запуск обучения
echo "[4/5] 🚀 Запуск обучения на A100..."
ssh $SERVER "cd $REMOTE_DIR/scripts && nohup python3 train_advanced_gpu.py > advanced_training.log 2>&1 &"
sleep 2
echo "✅ Обучение запущено в фоне"
echo ""

# Проверка статуса
echo "[5/5] 📊 Проверка статуса..."
ssh $SERVER "cd $REMOTE_DIR/scripts && tail -20 advanced_training.log" 2>/dev/null || echo "  (лог еще не создан)"
echo ""

echo "================================================"
echo "✅ ЗАПУСК ЗАВЕРШЕН"
echo "================================================"
echo ""
echo "⏱️  ОЖИДАЕМОЕ ВРЕМЯ: 5-10 минут"
echo ""
echo "📊 Для мониторинга прогресса:"
echo "  ssh $SERVER 'tail -f $REMOTE_DIR/scripts/advanced_training.log'"
echo ""
echo "🔍 Проверить статус через 5 минут:"
echo "  ssh $SERVER 'tail -50 $REMOTE_DIR/scripts/advanced_training.log'"
echo ""
echo "📥 Получить результаты:"
echo "  scp $SERVER:$REMOTE_DIR/scripts/advanced_training_results.json ."
echo "  scp $SERVER:$REMOTE_DIR/models/best_advanced_model_a100.pkl ../models/"
echo "  scp $SERVER:$REMOTE_DIR/models/ensemble_model_a100.pkl ../models/"
echo ""
echo "================================================"
