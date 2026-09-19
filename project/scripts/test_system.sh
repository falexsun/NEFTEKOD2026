#!/bin/bash
# Комплексный тест всей системы после запуска

set -e

# Цвета
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

API_URL="${API_URL:-http://localhost:8000}"
GRAFANA_URL="${GRAFANA_URL:-http://localhost:3000}"
PROMETHEUS_URL="${PROMETHEUS_URL:-http://localhost:9090}"

PASSED=0
FAILED=0

echo "=========================================="
echo "КОМПЛЕКСНОЕ ТЕСТИРОВАНИЕ СИСТЕМЫ"
echo "=========================================="
echo "API: $API_URL"
echo "Grafana: $GRAFANA_URL"
echo "Prometheus: $PROMETHEUS_URL"
echo ""

# Функция проверки HTTP
check_http() {
    local url=$1
    local name=$2
    local expected_code=${3:-200}

    echo -n "Проверка $name... "

    response=$(curl -s -o /dev/null -w "%{http_code}" "$url" 2>/dev/null || echo "000")

    if [ "$response" = "$expected_code" ]; then
        echo -e "${GREEN}✓${NC} (HTTP $response)"
        ((PASSED++))
        return 0
    else
        echo -e "${RED}✗${NC} (HTTP $response, ожидался $expected_code)"
        ((FAILED++))
        return 1
    fi
}

# Функция проверки JSON endpoint
check_json() {
    local url=$1
    local name=$2
    local jq_filter=$3

    echo -n "Проверка $name... "

    response=$(curl -s "$url" 2>/dev/null)

    if [ -z "$response" ]; then
        echo -e "${RED}✗${NC} (нет ответа)"
        ((FAILED++))
        return 1
    fi

    if echo "$response" | jq -e "$jq_filter" > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC}"
        ((PASSED++))
        return 0
    else
        echo -e "${RED}✗${NC} (некорректный JSON)"
        echo "Response: $response" | head -c 200
        ((FAILED++))
        return 1
    fi
}

# Функция проверки WebSocket
check_websocket() {
    local url=$1
    local name=$2

    echo -n "Проверка $name... "

    # Используем websocat если доступен, иначе пропускаем
    if command -v websocat &> /dev/null; then
        timeout 3 websocat "$url" > /dev/null 2>&1 && \
            echo -e "${GREEN}✓${NC}" && ((PASSED++)) || \
            echo -e "${YELLOW}⚠${NC} (не удалось подключиться)" && ((FAILED++))
    else
        echo -e "${YELLOW}⚠${NC} (websocat не установлен, пропускаем)"
    fi
}

echo "[1/8] Базовые health checks"
echo "─────────────────────────────────────────"
check_http "$API_URL/health" "API Health"
check_http "$API_URL/docs" "API Docs"
check_http "$GRAFANA_URL/api/health" "Grafana Health"
check_http "$PROMETHEUS_URL/-/healthy" "Prometheus Health"

echo ""
echo "[2/8] API Readiness"
echo "─────────────────────────────────────────"
check_json "$API_URL/ready" "Runtime Ready" ".ready"
check_json "$API_URL/ready" "Quality Model Ready" ".quality_model_ready"
check_json "$API_URL/ready" "Storage Ready" ".storage_ready"

echo ""
echo "[3/8] Q21 Shadow Pipeline"
echo "─────────────────────────────────────────"
check_json "$API_URL/q21/status" "Q21 Status" ".ready"
check_json "$API_URL/q21/runtime" "Q21 Runtime" ".required_points"
check_json "$API_URL/q21/runtime" "Q21 Data State" ".data_state"

echo ""
echo "[4/8] Timeline Events"
echo "─────────────────────────────────────────"
check_json "$API_URL/timeline/events?limit=5" "Timeline Events" ".events"
check_json "$API_URL/timeline/events?limit=5" "Timeline Count" ".count"

echo ""
echo "[5/8] Prometheus Metrics"
echo "─────────────────────────────────────────"
check_http "$API_URL/metrics" "Metrics Endpoint"

# Проверка конкретных метрик
echo -n "Проверка Q21 метрик... "
metrics=$(curl -s "$API_URL/metrics" 2>/dev/null)
if echo "$metrics" | grep -q "neftekod_q21_shadow_ready"; then
    echo -e "${GREEN}✓${NC} (Q21 метрики найдены)"
    ((PASSED++))
else
    echo -e "${RED}✗${NC} (Q21 метрики не найдены)"
    ((FAILED++))
fi

echo ""
echo "[6/8] WebSocket Connection"
echo "─────────────────────────────────────────"
check_websocket "ws://localhost:8000/ws/q21/live" "WebSocket /ws/q21/live"

echo ""
echo "[7/8] Модульная структура кода"
echo "─────────────────────────────────────────"

cd "$(dirname "$0")/.."

modules=(
    "src/api/websocket/__init__.py"
    "src/api/timeline/__init__.py"
    "src/api/notifications/__init__.py"
    "src/inference/anomaly/__init__.py"
    "src/inference/optimization/__init__.py"
)

for module in "${modules[@]}"; do
    if [ -f "$module" ]; then
        echo -e "${GREEN}✓${NC} $module"
        ((PASSED++))
    else
        echo -e "${RED}✗${NC} $module отсутствует"
        ((FAILED++))
    fi
done

echo ""
echo "[8/8] Интеграционный тест"
echo "─────────────────────────────────────────"

# Попробуем создать решение (если система готова)
echo -n "Тест: получение snapshot... "
snapshot=$(curl -s "$API_URL/snapshot" 2>/dev/null)
if echo "$snapshot" | jq -e ".readiness" > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC}"
    ((PASSED++))

    # Проверим режим данных
    mode=$(echo "$snapshot" | jq -r ".mode")
    echo "  Режим данных: $mode"

    # Проверим готовность компонентов
    ready=$(echo "$snapshot" | jq -r ".readiness.ready")
    echo "  Система готова: $ready"
else
    echo -e "${RED}✗${NC}"
    ((FAILED++))
fi

# Проверим demo endpoints (если доступны)
echo -n "Тест: demo scenarios... "
scenarios=$(curl -s "$API_URL/demo/scenarios" 2>/dev/null)
if echo "$scenarios" | jq -e ".scenarios" > /dev/null 2>&1; then
    count=$(echo "$scenarios" | jq -r ".scenarios | length")
    echo -e "${GREEN}✓${NC} ($count сценариев доступно)"
    ((PASSED++))
else
    echo -e "${YELLOW}⚠${NC} (demo endpoints недоступны)"
fi

echo ""
echo "=========================================="
echo "ИТОГО"
echo "=========================================="
echo -e "Успешно: ${GREEN}$PASSED${NC}"
echo -e "Провалено: ${RED}$FAILED${NC}"

if [ $FAILED -eq 0 ]; then
    echo ""
    echo -e "${GREEN}✅ ВСЕ ТЕСТЫ ПРОЙДЕНЫ!${NC}"
    echo ""
    echo "Система полностью работоспособна и готова к демонстрации."
    echo ""
    echo "Следующие шаги:"
    echo "1. Открыть Operator Console: $API_URL"
    echo "2. Открыть Grafana: $GRAFANA_URL"
    echo "3. Запустить demo replay:"
    echo "   uv run python scripts/demo_replay.py --scenario exceedance --speed 100"
    exit 0
else
    echo ""
    echo -e "${RED}❌ ЕСТЬ ПРОБЛЕМЫ${NC}"
    echo ""
    echo "Рекомендации:"
    echo "1. Проверить логи: docker compose logs gateway"
    echo "2. Проверить статус сервисов: docker compose ps"
    echo "3. Перезапустить систему: docker compose down && ./scripts/start_demo.sh"
    exit 1
fi
