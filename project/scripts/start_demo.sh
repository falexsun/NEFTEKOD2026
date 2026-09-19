#!/bin/bash
# Unified demo startup script for hackathon finale
# Starts all services and runs preflight check

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "=========================================="
echo "NEFTEKOD DEMO STARTUP"
echo "=========================================="

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Configuration
API_PORT="${NEFTEKOD_GATEWAY_PORT:-8000}"
GRAFANA_PORT="${GRAFANA_PORT:-3000}"
MONITORING_PROFILE="${MONITORING_PROFILE:-monitoring}"

echo -e "${YELLOW}[1/5] Проверка окружения...${NC}"

# Check Docker
if ! command -v docker &> /dev/null; then
    echo -e "${RED}✗ Docker не установлен${NC}"
    exit 1
fi

# Check Docker Compose
if ! command -v docker compose &> /dev/null; then
    echo -e "${RED}✗ Docker Compose не установлен${NC}"
    exit 1
fi

# Check data directory
if [ ! -d "$PROJECT_ROOT/../data" ] && [ ! -d "$PROJECT_ROOT/data" ]; then
    echo -e "${RED}✗ Директория data не найдена${NC}"
    echo "Создайте symlink: ln -s /path/to/data $PROJECT_ROOT/data"
    exit 1
fi

echo -e "${GREEN}✓ Окружение проверено${NC}"

echo -e "${YELLOW}[2/5] Сборка Docker образов...${NC}"
cd "$PROJECT_ROOT"
docker compose --profile "$MONITORING_PROFILE" build --quiet

echo -e "${GREEN}✓ Образы собраны${NC}"

echo -e "${YELLOW}[3/5] Запуск сервисов...${NC}"
docker compose --profile "$MONITORING_PROFILE" up -d

echo "Ожидание готовности сервисов..."
sleep 10

echo -e "${GREEN}✓ Сервисы запущены${NC}"

echo -e "${YELLOW}[4/5] Preflight проверка...${NC}"
if command -v uv &> /dev/null; then
    uv run python "$SCRIPT_DIR/preflight_check.py" \
        --api-url "http://localhost:$API_PORT" \
        --grafana-url "http://localhost:$GRAFANA_PORT" \
        --models-dir "$PROJECT_ROOT/models"
    PREFLIGHT_STATUS=$?
else
    python3 "$SCRIPT_DIR/preflight_check.py" \
        --api-url "http://localhost:$API_PORT" \
        --grafana-url "http://localhost:$GRAFANA_PORT" \
        --models-dir "$PROJECT_ROOT/models"
    PREFLIGHT_STATUS=$?
fi

if [ $PREFLIGHT_STATUS -eq 0 ]; then
    echo -e "${GREEN}✓ Preflight пройден${NC}"
else
    echo -e "${YELLOW}⚠ Preflight завершён с предупреждениями${NC}"
fi

echo -e "${YELLOW}[5/5] Статус сервисов${NC}"
docker compose ps

echo ""
echo "=========================================="
echo -e "${GREEN}DEMO STARTUP COMPLETE${NC}"
echo "=========================================="
echo ""
echo "Доступные endpoints:"
echo "  • Operator Console:  http://localhost:$API_PORT"
echo "  • API Gateway:       http://localhost:$API_PORT/docs"
echo "  • Demo Scenarios:    http://localhost:$API_PORT/demo/scenarios"
echo "  • Prometheus:        http://localhost:9090"
echo "  • Grafana:           http://localhost:$GRAFANA_PORT"
echo "  • Metrics:           http://localhost:$API_PORT/metrics"
echo ""
echo "Для запуска демо-сценария:"
echo "  uv run python scripts/demo_replay.py --scenario normal --speed 100"
echo "  uv run python scripts/demo_replay.py --scenario exceedance --speed 100"
echo ""
echo "После replay обновить презентационные цифры:"
echo "  uv run python scripts/update_presentation_stats.py"
echo ""
echo "Для остановки:"
echo "  docker compose --profile $MONITORING_PROFILE down"
echo ""
