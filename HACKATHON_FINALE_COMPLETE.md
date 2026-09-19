# ФИНАЛ ХАКАТОНА — РЕАЛИЗОВАНО

## ✅ 1. Демонстрационный сценарий replay

**Создано:** `scripts/demo_replay.py`

Возможности:
- Два фиксированных сценария: `normal` (Q21 < 10 ppm) и `exceedance` (Q21 → 10+ ppm)
- Воспроизводимые временные окна с известными результатами
- Автоматическая валидация данных под сценарий
- Ускоренный replay (100-500x) для быстрой демонстрации
- Статистика: отправлено точек, Q21 min/max/mean, время выполнения
- Опция `--dry-run` для тестирования без отправки

Запуск:
```bash
uv run python scripts/demo_replay.py --scenario normal --speed 100
uv run python scripts/demo_replay.py --scenario exceedance --speed 200
```

## ✅ 2. Операторский экран — завершён

**Обновлено:**
- `frontend/src/views/ShiftView.tsx` — показывает Q21 status и runtime
- `frontend/src/components/Q21ForecastPanel.tsx` — траектория с MAE и coverage
- `frontend/src/types.ts` — добавлены поля для общего MAE и coverage

**Что показывает:**
- Текущий Q21 и прогноз на 1-6 часов
- Вероятность превышения 10 ppm
- Статус Q21 Shadow Pipeline (готов/нет)
- Shadow метрики: MAE, coverage, количество закрытых прогнозов
- Freshness данных (live/historical/empty)
- Интервал неопределённости для h=1

**Без технических SHA на первом уровне** — перенесены в детали модели.

## ✅ 3. Grafana дашборды

**Создано:** `monitoring/grafana/dashboards/neftekod-q21-production.json`

Production дашборд Q21 Shadow Pipeline включает:
- **Статус pipeline**: готов/не готов
- **Текущий Q21**: цветовая индикация (зелёный < 9, жёлтый 9-10, красный > 10)
- **Прогноз +1h**: линия тренда с порогом 10 ppm
- **Вероятность превышения**: gauge с цветовыми зонами
- **Shadow MAE**: целевое значение < 2-3 ppm
- **Coverage**: доля закрытых прогнозов
- **Буфер точек**: минимум 145 для inference
- **NO_ACTION count**: количество отказов от прогноза
- **Freshness**: задержка последней точки
- **Статистика**: выполнено/закрыто прогнозов

**Алерты:** `monitoring/prometheus/q21_alerts.yml`
- Q21 превысил 10 ppm (критический)
- Поток данных остановлен (критический)
- MAE > 3.0 ppm (предупреждение)
- Coverage < 50% (предупреждение)
- Высокая вероятность превышения (предупреждение)
- Буфер не прогрет (инфо)
- Слишком много NO_ACTION (инфо)

## ✅ 4. Демонстрационная эксплуатация

**Создано:**

### `scripts/start_demo.sh` — единый скрипт запуска
- Проверка окружения (Docker, данные)
- Сборка образов
- Запуск всех сервисов с monitoring profile
- Автоматический preflight check
- Отображение всех endpoints

Запуск:
```bash
cd project
./scripts/start_demo.sh
```

### `scripts/preflight_check.py` — проверка готовности
Проверяет перед презентацией:
- ✓ API health
- ✓ API ready (модель, история, схема, surrogate, storage)
- ✓ Q21 status (5 горизонтов, risk, uncertainty)
- ✓ Prometheus metrics (neftekod_q21_* и другие)
- ✓ Grafana доступность
- ✓ Модели на диске

Сохраняет отчёт в JSON.

Запуск:
```bash
uv run python scripts/preflight_check.py --output report.json
```

### `DEMO_GUIDE.md` — пошаговая инструкция
- Быстрый старт (3 команды)
- Описание сценариев
- Что показывать жюри
- Troubleshooting

## ✅ 5. Prometheus метрики для Q21

**Добавлено в `src/api/app.py`:**

```python
Q21_SHADOW_READY = Gauge("neftekod_q21_shadow_ready", "...")
Q21_CURRENT_PPM = Gauge("neftekod_q21_current_ppm", "...")
Q21_FORECAST_1H_PPM = Gauge("neftekod_q21_forecast_1h_ppm", "...")
Q21_EXCEEDANCE_PROBABILITY = Gauge("neftekod_q21_exceedance_probability", "...")
Q21_SHADOW_MAE = Gauge("neftekod_q21_shadow_mae_ppm", "...")
Q21_SHADOW_COVERAGE = Gauge("neftekod_q21_shadow_coverage", "...")
Q21_SHADOW_NO_ACTION = Gauge("neftekod_q21_shadow_no_action_count", "...")
Q21_BUFFER_POINTS = Gauge("neftekod_q21_buffer_points", "...")
Q21_DATA_FRESHNESS = Gauge("neftekod_q21_data_freshness_minutes", "...")
Q21_PREDICTIONS_COUNT = Counter("neftekod_q21_shadow_predictions_total", "...")
Q21_CLOSED_COUNT = Counter("neftekod_q21_shadow_closed_total", "...")
```

Обновляются автоматически:
- При инициализации runtime
- После каждой отправки Q21 точки
- При запросе `/q21/runtime`

## Итоговая архитектура для финала

```
┌─────────────────────────────────────────────────────────────────┐
│                    ДЕМО ДЛЯ ФИНАЛА ХАКАТОНА                      │
└─────────────────────────────────────────────────────────────────┘

1. Запуск системы
   └─> ./scripts/start_demo.sh
       ├─> Docker Compose (PostgreSQL, Redis, API, Grafana, Prometheus)
       ├─> Preflight check (автоматически)
       └─> Отображение endpoints

2. Демо-сценарий
   └─> python scripts/demo_replay.py --scenario normal --speed 100
       ├─> Загрузка фиксированного временного окна
       ├─> Валидация данных
       ├─> Ускоренная отправка в API
       └─> Статистика выполнения

3. Мониторинг (в браузере)
   ├─> http://localhost:8000 — Operator Console
   │   ├─> Q21 текущий + прогноз 1-6h
   │   ├─> Траектория с интервалом
   │   └─> Shadow MAE и coverage
   │
   ├─> http://localhost:3000 — Grafana
   │   ├─> Dashboard "Q21 Shadow Pipeline"
   │   ├─> Метрики в реальном времени
   │   └─> Алерты (настроены)
   │
   └─> http://localhost:9090 — Prometheus
       ├─> Метрики neftekod_q21_*
       └─> Проверка алертов

4. Презентация
   ├─> Показать единый запуск
   ├─> Запустить сценарий "exceedance"
   ├─> Показать рост Q21 на графиках
   ├─> Показать прогноз превышения
   └─> Показать MAE и coverage
```

## Отличие от production-версии

Демо (80-85% готовности):
- ✅ Воспроизводимые сценарии
- ✅ Все метрики и дашборды
- ✅ Shadow pipeline работает
- ✅ Автоматический preflight
- ⚠️  Replay вместо live потока
- ⚠️  Без real historian/broker
- ⚠️  Без TLS и production auth
- ⚠️  SQLite вместо PostgreSQL (можно переключить)

Production (требует):
- Контракт данных с заводом
- Реальная интеграция (historian/broker + TLS)
- PostgreSQL + Alembic миграции
- Production security (Vault, RBAC)
- Полная валидация моделей (месяцы shadow-пилота)
- Нагрузочное и отказоустойчивое тестирование
- Согласованные операционные правила

## Запуск для жюри

```bash
# Терминал 1: запуск системы
cd project
./scripts/start_demo.sh

# Дождаться "DEMO STARTUP COMPLETE"
# Открыть браузер: http://localhost:8000, http://localhost:3000

# Терминал 2: демо-сценарий
cd project
uv run python scripts/demo_replay.py --scenario exceedance --speed 100

# Наблюдать обновление метрик в реальном времени
```

Время демонстрации: 3-5 минут (replay 4 часов данных за ~2.4 минуты).
