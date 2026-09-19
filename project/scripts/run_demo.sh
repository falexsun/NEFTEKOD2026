#!/bin/bash
# Освобождение порта 8000 и запуск демонстрации

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo "=========================================="
echo "ОСВОБОЖДЕНИЕ ПОРТА 8000 И ЗАПУСК ДЕМО"
echo "=========================================="

# 1. Найти и остановить процесс на порту 8000
echo ""
echo "[1/5] Освобождение порта 8000..."

PID=$(lsof -ti :8000 2>/dev/null || echo "")

if [ -n "$PID" ]; then
    echo "Найден процесс на порту 8000: PID=$PID"

    # Проверить это Docker контейнер
    CONTAINER=$(docker ps --format "{{.ID}} {{.Names}}" 2>/dev/null | grep -v "project-" | head -1 || echo "")

    if [ -n "$CONTAINER" ]; then
        CONTAINER_ID=$(echo $CONTAINER | awk '{print $1}')
        CONTAINER_NAME=$(echo $CONTAINER | awk '{print $2}')
        echo "Останавливаю контейнер: $CONTAINER_NAME"
        docker stop $CONTAINER_ID
        echo -e "${GREEN}✓${NC} Контейнер остановлен"
    else
        echo "Останавливаю процесс: PID=$PID"
        kill $PID 2>/dev/null || echo "Процесс уже остановлен"
        sleep 2
    fi
else
    echo -e "${GREEN}✓${NC} Порт 8000 свободен"
fi

# 2. Запуск системы
echo ""
echo "[2/5] Запуск Нефтекод системы..."
cd "$(dirname "$0")/.."
docker compose up -d

echo "Ожидание запуска контейнеров (15 секунд)..."
sleep 15

# 3. Проверка health
echo ""
echo "[3/5] Проверка работоспособности..."

if curl -s http://localhost:8000/health >/dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} API доступен на http://localhost:8000"
else
    echo -e "${RED}✗${NC} API не отвечает"
    exit 1
fi

# 4. Проверка новых endpoints
echo ""
echo "[4/5] Проверка новых фич..."

# Timeline
if curl -s http://localhost:8000/timeline/events >/dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} Timeline Events API работает"
else
    echo -e "${YELLOW}⚠${NC} Timeline Events недоступен"
fi

# Demo scenarios
if curl -s http://localhost:8000/demo/scenarios >/dev/null 2>&1; then
    SCENARIOS=$(curl -s http://localhost:8000/demo/scenarios | jq '.scenarios | length' 2>/dev/null || echo "0")
    echo -e "${GREEN}✓${NC} Demo Scenarios API работает ($SCENARIOS сценариев)"
else
    echo -e "${YELLOW}⚠${NC} Demo Scenarios недоступен"
fi

# 5. Запуск demo replay
echo ""
echo "[5/5] Запуск демонстрационного сценария..."
echo ""
echo "Запускаю сценарий 'exceedance' (Q21 превышает 10 ppm)..."
echo "Скорость: 100x (4 часа за ~2.4 минуты)"
echo ""

uv run python scripts/demo_replay.py --scenario exceedance --speed 100

echo ""
echo "=========================================="
echo -e "${GREEN}ДЕМОНСТРАЦИЯ ЗАВЕРШЕНА${NC}"
echo "=========================================="
echo ""
echo "Система работает:"
echo "  • Operator Console: http://localhost:8000"
echo "  • Grafana:          http://localhost:3000"
echo "  • Prometheus:       http://localhost:9090"
echo ""
echo "Проверьте Timeline events:"
echo "  curl http://localhost:8000/timeline/events | jq '.'"
echo ""
echo "Для остановки:"
echo "  docker compose down"
echo ""
