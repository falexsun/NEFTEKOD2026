# Демонстрационный сценарий для финала хакатона

## Быстрый старт

### 1. Запуск всей системы

```bash
cd project
./scripts/start_demo.sh
```

Скрипт:
- Проверит окружение (Docker, Docker Compose, данные)
- Соберёт образы
- Запустит все сервисы (PostgreSQL, Redis, API, Grafana, Prometheus)
- Выполнит preflight проверку
- Покажет статус всех компонентов

### 2. Демо-сценарии replay

После запуска системы, в отдельном терминале:

**Сценарий 1: Нормальный режим** (Q21 стабильно < 10 ppm)
```bash
cd project
uv run python scripts/demo_replay.py --scenario normal --speed 100
```

**Сценарий 2: Превышение Q21** (Q21 растёт к 10+ ppm)
```bash
cd project
uv run python scripts/demo_replay.py --scenario exceedance --speed 100
```

Параметры:
- `--speed 100` — ускорение в 100 раз (4 часа данных за ~2.4 минуты)
- `--speed 200` — ускорение в 200 раз (ещё быстрее для демо)
- `--dry-run` — не отправлять данные, только показать

### 3. Мониторинг во время replay

Откройте в браузере:

- **Operator Console**: http://localhost:8000
  - Смотрите обновление Q21 в реальном времени
  - Прогнозы на 1-6 часов вперёд
  - Shadow MAE и coverage

- **Grafana Q21 Dashboard**: http://localhost:3000/d/neftekod-q21-production
  - Текущий Q21 и прогноз +1h
  - Вероятность превышения
  - MAE, coverage, NO_ACTION count
  - Freshness данных

- **Prometheus**: http://localhost:9090
  - Метрики `neftekod_q21_*`
  - Алерты (настроены, но не отправляются в хакатонной версии)

### 4. Preflight перед презентацией

```bash
uv run python scripts/preflight_check.py
```

Проверит:
- ✓ API health
- ✓ Runtime готовность
- ✓ Q21 pipeline статус
- ✓ Prometheus metrics
- ✓ Grafana доступность
- ✓ Модели на диске

### 5. Остановка

```bash
docker compose --profile monitoring down
```

Или остановить только контейнеры, сохранив данные:
```bash
docker compose --profile monitoring stop
```

## Демонстрационные сценарии

### Сценарий "normal"
- Период: 2023-06-15 08:00 — 12:00 (4 часа, ~24 точки)
- Q21 диапазон: 7.5 — 9.5 ppm
- Ожидаемый MAE: < 2.0 ppm
- Показывает: стабильный режим, низкая вероятность превышения

### Сценарий "exceedance"
- Период: 2023-08-22 14:00 — 18:00 (4 часа, ~24 точки)
- Q21 диапазон: 9.0 — 11.5 ppm
- Q21 пересекает порог 10 ppm
- Показывает: рост Q21, прогноз превышения, реакция системы

## Что показывать жюри

1. **Единый запуск** — `./scripts/start_demo.sh` (всё в одной команде)
2. **Preflight** — автоматическая проверка готовности
3. **Replay сценарий** — воспроизводимая демонстрация с фиксированными данными
4. **Operator Console** — React интерфейс с Q21 траекторией
5. **Grafana Q21 Dashboard** — production дашборд с метриками
6. **Shadow Metrics** — MAE, coverage, количество прогнозов в реальном времени

## Особенности демо-режима

- **Воспроизводимость**: фиксированные временные окна с известными результатами
- **Скорость**: ускоренный replay (100-200x) для быстрой демонстрации
- **Валидация**: автоматическая проверка, что данные соответствуют сценарию
- **Метрики**: реальные Prometheus метрики, обновляемые в процессе replay
- **Идемпотентность**: повторный запуск с теми же параметрами даёт те же результаты

## Troubleshooting

**Порт 8000 занят:**
```bash
export NEFTEKOD_GATEWAY_PORT=8001
./scripts/start_demo.sh
```

**Нет данных:**
```bash
# Создайте symlink на директорию с data
ln -s /path/to/data project/data
```

**Preflight failed:**
- Проверьте логи: `docker compose logs gateway`
- Проверьте модели: `ls -la project/models/`
- Проверьте БД: `docker compose logs postgres`

**Grafana не показывает данные:**
- Дайте системе прогреться (1-2 минуты после старта)
- Запустите demo replay, чтобы появились метрики
- Проверьте Prometheus targets: http://localhost:9090/targets
