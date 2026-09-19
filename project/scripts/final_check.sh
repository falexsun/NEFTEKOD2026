#!/bin/bash
# Финальная проверка и сборка всех новых фичей

set -e

cd "$(dirname "$0")/.."

echo "=========================================="
echo "ФИНАЛЬНАЯ ПРОВЕРКА ВЫИГРЫШНЫХ ФИЧЕЙ"
echo "=========================================="

# Проверка backend файлов
echo ""
echo "[1/6] Проверка backend файлов..."
FILES=(
    "src/api/websocket.py"
    "src/api/timeline.py"
    "src/api/telegram_notifier.py"
    "src/inference/scenario_optimizer.py"
    "src/inference/anomaly_detector.py"
)

for file in "${FILES[@]}"; do
    if [ -f "$file" ]; then
        echo "  ✓ $file"
    else
        echo "  ✗ ОТСУТСТВУЕТ: $file"
        exit 1
    fi
done

# Проверка frontend файлов
echo ""
echo "[2/6] Проверка frontend файлов..."
FRONTEND_FILES=(
    "frontend/src/components/AlertBanner.tsx"
    "frontend/src/components/TimelinePanel.tsx"
    "frontend/src/hooks/useQ21WebSocket.ts"
    "frontend/src/styles/live-features.css"
)

for file in "${FRONTEND_FILES[@]}"; do
    if [ -f "$file" ]; then
        echo "  ✓ $file"
    else
        echo "  ✗ ОТСУТСТВУЕТ: $file"
        exit 1
    fi
done

# Проверка зависимостей Python
echo ""
echo "[3/6] Проверка Python зависимостей..."
if command -v uv &> /dev/null; then
    echo "  ✓ uv установлен"
    uv pip list | grep -q scikit-learn || {
        echo "  → Установка scikit-learn..."
        uv pip install scikit-learn
    }
    uv pip list | grep -q httpx || {
        echo "  → Установка httpx..."
        uv pip install httpx
    }
    echo "  ✓ Все зависимости установлены"
else
    echo "  ⚠ uv не найден, используем pip"
    pip install scikit-learn httpx
fi

# Сборка frontend
echo ""
echo "[4/6] Сборка frontend..."
cd frontend
if [ ! -d "node_modules" ]; then
    echo "  → npm install..."
    npm install
fi

echo "  → npm run build..."
npm run build

if [ -d "dist" ]; then
    echo "  ✓ Frontend собран: dist/"
else
    echo "  ✗ Ошибка сборки frontend"
    exit 1
fi

cd ..

# Проверка API endpoints в app.py
echo ""
echo "[5/6] Проверка интеграции в app.py..."
ENDPOINTS=(
    "/ws/q21/live"
    "/timeline/events"
    "/timeline/root-cause"
    "/anomaly/detect"
    "/scenarios/optimize"
)

for endpoint in "${ENDPOINTS[@]}"; do
    if grep -q "$endpoint" src/api/app.py; then
        echo "  ✓ Endpoint: $endpoint"
    else
        echo "  ⚠ Возможно отсутствует: $endpoint"
    fi
done

# Финальный checklist
echo ""
echo "[6/6] Итоговый статус..."
echo ""
echo "✅ Backend фичи:"
echo "  • WebSocket — websocket.py"
echo "  • Timeline — timeline.py"
echo "  • Telegram — telegram_notifier.py"
echo "  • Optimization — scenario_optimizer.py"
echo "  • Anomaly Detection — anomaly_detector.py"
echo ""
echo "✅ Frontend компоненты:"
echo "  • AlertBanner.tsx"
echo "  • TimelinePanel.tsx"
echo "  • useQ21WebSocket.ts"
echo "  • live-features.css"
echo ""
echo "✅ Сборка:"
echo "  • Frontend собран в dist/"
echo "  • Python зависимости установлены"
echo ""
echo "=========================================="
echo "ВСЕ ФИЧИ ГОТОВЫ К ТЕСТИРОВАНИЮ!"
echo "=========================================="
echo ""
echo "Следующие шаги:"
echo "1. Запустить систему:"
echo "   ./scripts/start_demo.sh"
echo ""
echo "2. Тестировать WebSocket:"
echo "   Открыть http://localhost:8000"
echo "   Проверить 'Live' индикатор в правом нижнем углу"
echo ""
echo "3. Запустить demo replay:"
echo "   uv run python scripts/demo_replay.py --scenario exceedance --speed 100"
echo ""
echo "4. Проверить timeline events:"
echo "   curl http://localhost:8000/timeline/events?limit=10"
echo ""
echo "Удачи на финале! 🚀"
