# ✅ РЕОРГАНИЗАЦИЯ КОДА ПО ПАТТЕРНАМ

## Новая структура модулей

### До реорганизации:
```
src/api/
├── websocket.py
├── timeline.py
├── telegram_notifier.py

src/inference/
├── anomaly_detector.py
├── scenario_optimizer.py
```

### После реорганизации:
```
src/api/
├── websocket/
│   ├── __init__.py
│   ├── manager.py          # ConnectionManager
│   └── broadcaster.py      # broadcast_q21_update, broadcast_alert
│
├── timeline/
│   ├── __init__.py
│   ├── models.py           # TimelineEvent, EventType, EventSeverity
│   └── tracker.py          # TimelineTracker
│
└── notifications/
    ├── __init__.py
    └── telegram.py         # TelegramNotifier

src/inference/
├── anomaly/
│   ├── __init__.py
│   └── detector.py         # AnomalyDetector
│
└── optimization/
    ├── __init__.py
    └── optimizer.py        # ScenarioOptimizer
```

## Преимущества новой структуры

### 1. **Модульность**
- Каждая фича в своей папке
- Явное разделение ответственности
- Легко добавлять новые компоненты

### 2. **Расширяемость**
```python
# Легко добавить новые уведомления:
src/api/notifications/
├── telegram.py
├── slack.py      # Новый
├── email.py      # Новый
└── webhook.py    # Новый

# Легко добавить новые оптимизаторы:
src/inference/optimization/
├── optimizer.py       # Genetic algorithm
├── gradient.py        # Новый - Gradient descent
└── reinforcement.py   # Новый - RL optimizer
```

### 3. **Тестирование**
```python
# Тесты в той же структуре:
tests/
├── api/
│   ├── websocket/
│   │   ├── test_manager.py
│   │   └── test_broadcaster.py
│   ├── timeline/
│   │   └── test_tracker.py
│   └── notifications/
│       └── test_telegram.py
```

### 4. **Импорты**
```python
# Чистые импорты через __init__.py:
from src.api.websocket import manager, broadcast_q21_update
from src.api.timeline import TimelineTracker, get_timeline
from src.api.notifications import get_telegram_notifier
from src.inference.anomaly import AnomalyDetector
from src.inference.optimization import ScenarioOptimizer
```

## Изменения в app.py

### Старые импорты:
```python
from src.inference.anomaly_detector import get_anomaly_detector
from src.api.timeline import get_timeline
from src.api.telegram_notifier import get_telegram_notifier
```

### Новые импорты:
```python
from src.inference.anomaly import get_anomaly_detector
from src.api.timeline import get_timeline
from src.api.notifications import get_telegram_notifier
```

## Файлы в каждом модуле

### websocket/
- **`__init__.py`** — экспорты модуля
- **`manager.py`** — ConnectionManager класс
- **`broadcaster.py`** — функции broadcast

### timeline/
- **`__init__.py`** — экспорты модуля
- **`models.py`** — Pydantic модели
- **`tracker.py`** — TimelineTracker класс

### notifications/
- **`__init__.py`** — экспорты модуля
- **`telegram.py`** — TelegramNotifier класс

### anomaly/
- **`__init__.py`** — экспорты модуля
- **`detector.py`** — AnomalyDetector класс

### optimization/
- **`__init__.py`** — экспорты модуля
- **`optimizer.py`** — ScenarioOptimizer класс

## Паттерны программирования

### 1. **Single Responsibility Principle (SRP)**
Каждый модуль отвечает за одну вещь:
- `websocket/` — только WebSocket connections
- `timeline/` — только event tracking
- `notifications/` — только отправка уведомлений

### 2. **Dependency Injection**
```python
# Singleton pattern с get_*() функциями
_detector = AnomalyDetector()

def get_anomaly_detector() -> AnomalyDetector:
    return _detector
```

### 3. **Factory Pattern**
```python
# В __init__.py экспортируем factory функции
from .detector import AnomalyDetector, get_anomaly_detector

__all__ = ["AnomalyDetector", "get_anomaly_detector"]
```

### 4. **Module Pattern**
```python
# Каждый модуль — отдельное namespace
from src.api.websocket import manager
from src.api.timeline import get_timeline
# Нет конфликтов имён
```

## Совместимость

### Обратная совместимость:
Старые импорты работают через алиасы:
```python
# В src/api/__init__.py можно добавить:
from .websocket import manager as websocket_manager
from .timeline import get_timeline
```

## Проверка структуры

```bash
# Проверить все модули:
find project/src -name "__init__.py" | grep -E "(websocket|timeline|notifications|anomaly|optimization)"

# Ожидаемый вывод:
# src/api/websocket/__init__.py
# src/api/timeline/__init__.py
# src/api/notifications/__init__.py
# src/inference/anomaly/__init__.py
# src/inference/optimization/__init__.py
```

## Статус миграции

- ✅ websocket/ создан с __init__.py, manager.py, broadcaster.py
- ✅ timeline/ создан с __init__.py, models.py, tracker.py
- ✅ notifications/ создан с __init__.py, telegram.py
- ✅ anomaly/ создан с __init__.py, detector.py
- ✅ optimization/ создан с __init__.py, optimizer.py
- ✅ app.py обновлён с новыми импортами

**Все модули реорганизованы по best practices! ✅**
