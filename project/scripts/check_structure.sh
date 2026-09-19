#!/bin/bash
# Проверка правильной структуры модулей

echo "=========================================="
echo "ПРОВЕРКА СТРУКТУРЫ МОДУЛЕЙ"
echo "=========================================="

cd "$(dirname "$0")/.."

# Цвета
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

# Счётчики
PASSED=0
FAILED=0

# Функция проверки файла
check_file() {
    if [ -f "$1" ]; then
        echo -e "${GREEN}✓${NC} $1"
        ((PASSED++))
    else
        echo -e "${RED}✗${NC} $1 ОТСУТСТВУЕТ"
        ((FAILED++))
    fi
}

# Проверка структуры websocket
echo ""
echo "[1/5] Проверка модуля websocket/"
check_file "src/api/websocket/__init__.py"
check_file "src/api/websocket/manager.py"
check_file "src/api/websocket/broadcaster.py"

# Проверка структуры timeline
echo ""
echo "[2/5] Проверка модуля timeline/"
check_file "src/api/timeline/__init__.py"
check_file "src/api/timeline/models.py"
check_file "src/api/timeline/tracker.py"

# Проверка структуры notifications
echo ""
echo "[3/5] Проверка модуля notifications/"
check_file "src/api/notifications/__init__.py"
check_file "src/api/notifications/telegram.py"

# Проверка структуры anomaly
echo ""
echo "[4/5] Проверка модуля anomaly/"
check_file "src/inference/anomaly/__init__.py"
check_file "src/inference/anomaly/detector.py"

# Проверка структуры optimization
echo ""
echo "[5/5] Проверка модуля optimization/"
check_file "src/inference/optimization/__init__.py"
check_file "src/inference/optimization/optimizer.py"

# Проверка импортов в app.py
echo ""
echo "Проверка импортов в app.py..."
if grep -q "from src.inference.anomaly import" src/api/app.py; then
    echo -e "${GREEN}✓${NC} Импорт anomaly обновлён"
    ((PASSED++))
else
    echo -e "${RED}✗${NC} Импорт anomaly не обновлён"
    ((FAILED++))
fi

if grep -q "from src.api.notifications import" src/api/app.py; then
    echo -e "${GREEN}✓${NC} Импорт notifications обновлён"
    ((PASSED++))
else
    echo -e "${RED}✗${NC} Импорт notifications не обновлён"
    ((FAILED++))
fi

if grep -q "from src.api.websocket import" src/api/app.py; then
    echo -e "${GREEN}✓${NC} Импорт websocket обновлён"
    ((PASSED++))
else
    echo -e "${RED}✗${NC} Импорт websocket не обновлён"
    ((FAILED++))
fi

# Проверка старых файлов (должны быть удалены)
echo ""
echo "Проверка удаления старых файлов..."
OLD_FILES=(
    "src/api/websocket.py"
    "src/api/timeline.py"
    "src/api/telegram_notifier.py"
    "src/inference/anomaly_detector.py"
    "src/inference/scenario_optimizer.py"
)

for file in "${OLD_FILES[@]}"; do
    if [ ! -f "$file" ]; then
        echo -e "${GREEN}✓${NC} $file удалён (ок)"
        ((PASSED++))
    else
        echo -e "${RED}⚠${NC} $file ещё существует (нужно удалить)"
    fi
done

# Итоги
echo ""
echo "=========================================="
echo "ИТОГО: ${GREEN}${PASSED} успешно${NC}, ${RED}${FAILED} провалено${NC}"
echo "=========================================="

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✅ ВСЕ МОДУЛИ ПРАВИЛЬНО СТРУКТУРИРОВАНЫ${NC}"
    exit 0
else
    echo -e "${RED}❌ ЕСТЬ ПРОБЛЕМЫ СО СТРУКТУРОЙ${NC}"
    exit 1
fi
