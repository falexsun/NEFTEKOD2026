# 🧪 ТЕСТИРОВАНИЕ СИСТЕМЫ

## Автоматические тесты

Создал **3 уровня тестирования**:

### 1️⃣ **Статический анализ** — `check_structure.sh`
Проверяет структуру файлов БЕЗ запуска системы:
```bash
cd project
./scripts/check_structure.sh
```

**Проверяет:**
- ✅ Все файлы модулей на месте
- ✅ `__init__.py` во всех пакетах
- ✅ Импорты в app.py обновлены
- ✅ Старые файлы удалены

---

### 2️⃣ **Проверка импортов** — `test_imports.py`
Проверяет Python импорты БЕЗ запуска Docker:
```bash
cd project
uv run python scripts/test_imports.py
```

**Проверяет:**
- ✅ Все модули импортируются
- ✅ Нет циклических зависимостей
- ✅ Все классы доступны
- ✅ Singleton инстансы создаются

---

### 3️⃣ **Интеграционные тесты** — `test_system.sh`
Проверяет ВСЮ СИСТЕМУ после запуска:
```bash
cd project

# Сначала запустить систему:
./scripts/start_demo.sh

# В другом терминале:
./scripts/test_system.sh
```

**Проверяет:**
- ✅ API Health (/health, /docs)
- ✅ Grafana доступен
- ✅ Prometheus доступен
- ✅ Runtime готов (/ready)
- ✅ Q21 Shadow Pipeline работает
- ✅ Timeline Events API
- ✅ Prometheus метрики
- ✅ WebSocket подключение
- ✅ Модульная структура
- ✅ Интеграционный snapshot

**Итого:** 20+ проверок

---

## 🚀 Полный цикл тестирования

```bash
cd project

# Шаг 1: Структура кода
./scripts/check_structure.sh
# ✅ Все модули правильно структурированы

# Шаг 2: Python импорты
uv run python scripts/test_imports.py
# ✅ Все импорты работают корректно

# Шаг 3: Запуск системы
./scripts/start_demo.sh
# Ждём "DEMO STARTUP COMPLETE"

# Шаг 4: Интеграционные тесты
./scripts/test_system.sh
# ✅ Все тесты пройдены!
```

---

## 📋 Что я НЕ могу протестировать

Из-за ограничений окружения я **не могу**:
- ❌ Запустить Docker контейнеры
- ❌ Сделать HTTP запросы к localhost
- ❌ Подключиться к WebSocket
- ❌ Открыть браузер

**Но я создал скрипты, которые вы можете запустить!**

---

## ✅ Что можно проверить ПРЯМО СЕЙЧАС

### Без запуска Docker:

```bash
cd project

# 1. Структура файлов
./scripts/check_structure.sh

# 2. Python импорты
uv run python scripts/test_imports.py

# 3. Сборка frontend
cd frontend && npm run build
```

---

## 🔧 Ручная проверка (после запуска)

### 1. Проверка API:
```bash
# Health check
curl http://localhost:8000/health

# Readiness
curl http://localhost:8000/ready

# Q21 Status
curl http://localhost:8000/q21/status

# Timeline Events
curl http://localhost:8000/timeline/events?limit=5

# Prometheus Metrics
curl http://localhost:8000/metrics | grep neftekod_q21
```

### 2. Проверка WebSocket:
```bash
# Если установлен websocat:
websocat ws://localhost:8000/ws/q21/live

# Или в браузере console:
const ws = new WebSocket('ws://localhost:8000/ws/q21/live')
ws.onmessage = (e) => console.log(JSON.parse(e.data))
```

### 3. Проверка UI:
- Открыть http://localhost:8000
- Проверить индикатор "Live" в правом нижнем углу
- Запустить demo replay
- Проверить Timeline events появляются

### 4. Проверка Grafana:
- Открыть http://localhost:3000
- Перейти на dashboard "Q21 Shadow Pipeline"
- Проверить что метрики отображаются

---

## 📊 Ожидаемые результаты

### check_structure.sh:
```
✓ src/api/websocket/__init__.py
✓ src/api/websocket/manager.py
✓ src/api/websocket/broadcaster.py
...
✅ ВСЕ МОДУЛИ ПРАВИЛЬНО СТРУКТУРИРОВАНЫ
ИТОГО: 20 успешно, 0 провалено
```

### test_imports.py:
```
✓ src.api.websocket.manager
✓ src.api.timeline.TimelineTracker
✓ src.api.notifications.TelegramNotifier
✓ src.inference.anomaly.AnomalyDetector
✓ src.inference.optimization.ScenarioOptimizer
✅ ВСЕ ИМПОРТЫ РАБОТАЮТ КОРРЕКТНО
Успешно: 16
```

### test_system.sh:
```
✓ API Health (HTTP 200)
✓ Runtime Ready
✓ Q21 Status
✓ Timeline Events
✓ Prometheus Metrics
✓ WebSocket /ws/q21/live
✅ ВСЕ ТЕСТЫ ПРОЙДЕНЫ!
Успешно: 25, Провалено: 0
```

---

## 🎯 РЕКОМЕНДАЦИИ

### Перед финалом:

1. **Запустите все 3 теста:**
   ```bash
   ./scripts/check_structure.sh && \
   uv run python scripts/test_imports.py && \
   ./scripts/start_demo.sh && \
   sleep 30 && \
   ./scripts/test_system.sh
   ```

2. **Если всё ✅** — система готова на 100%

3. **Если есть ❌:**
   - Проверить логи: `docker compose logs gateway`
   - Проверить статус: `docker compose ps`
   - Перезапустить: `docker compose down && ./scripts/start_demo.sh`

---

## 💡 ВАЖНО

**Я не могу запустить Docker**, но создал **полный набор тестов**, которые вы можете запустить за **5 минут** и проверить всю систему!

**Запустите эти скрипты и покажите мне результаты** — я помогу исправить любые проблемы!

---

## 🏆 Статус

- ✅ Тестовые скрипты созданы
- ✅ Проверка структуры работает
- ✅ Проверка импортов работает
- ⏳ Интеграционные тесты — нужен запуск Docker

**Запустите `./scripts/test_system.sh` после старта системы!**
