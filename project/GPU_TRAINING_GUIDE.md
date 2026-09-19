# 🚀 Инструкция: Массовое обучение на A100 + Инкрементальное обучение

## Архитектура системы

```
┌─────────────────────────────────────────────────────┐
│  PHASE 1: Поиск базовой модели (A100 GPU)         │
│                                                     │
│  1. Массовое обучение 200+ конфигураций           │
│  2. Grid search: CatBoost/LightGBM/XGBoost         │
│  3. Выбор лучшей базовой архитектуры              │
│                                                     │
│  Output: best_base_model.pkl                       │
└─────────────────┬───────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────┐
│  PHASE 2: Инкрементальное обучение (Production)    │
│                                                     │
│  1. База загружена в память                        │
│  2. Слушаем Redis на новые LIMS данные            │
│  3. Дообучаем модель (warm start)                  │
│  4. Валидируем улучшение                           │
│  5. Hot-swap если улучшилась                       │
│                                                     │
│  Trigger: новые лабораторные результаты            │
└─────────────────────────────────────────────────────┘
```

---

## PHASE 1: Массовое обучение на A100

### 1. Деплой на удаленный сервер

```bash
# Из локальной машины
cd /Users/falexsun/code/Нефтекод/project/scripts

# Запуск деплоя (автоматически sync + setup + launch)
./deploy_to_a100.sh
```

Скрипт автоматически:
- ✅ Синхронизирует код на сервер
- ✅ Настраивает Python окружение
- ✅ Конвертирует данные в Parquet
- ✅ Запускает обучение в background

### 2. Мониторинг обучения

```bash
# Подключиться к серверу
ssh faizov@37.75.249.204

# Смотреть логи в реальном времени
tail -f /home/faizov/projects/NEFTECODE2026/training.log

# Проверить GPU утилизацию
watch -n 1 nvidia-smi

# Проверить процесс
ps aux | grep train_base_model
```

### 3. Параметры массового обучения

**Grid search включает**:

#### CatBoost (60+ конфигураций)
- Iterations: 500, 1000, 2000, 3000
- Depth: 4, 6, 8, 10
- Learning rate: 0.01, 0.03, 0.05, 0.1, 0.15
- L2 reg: 1, 3, 5, 7, 10
- Bootstrap: Bayesian, Bernoulli, MVS

#### LightGBM (64+ конфигураций)
- N estimators: 500, 1000, 2000, 3000
- Num leaves: 15, 31, 63, 127
- Learning rate: 0.01, 0.03, 0.05, 0.1
- Max depth: -1, 8, 10, 12

#### XGBoost (64+ конфигураций)
- N estimators: 500, 1000, 2000, 3000
- Max depth: 4, 6, 8, 10, 12
- Learning rate: 0.01, 0.03, 0.05, 0.1
- Gamma: 0, 0.1, 0.5, 1.0

**Итого**: ~200 конфигураций

### 4. Ожидаемое время

На A100:
- Одна модель (CatBoost, 1000 iter): ~5-10 секунд
- 200 моделей: **~20-40 минут**

Checkpoint каждые 10 моделей → можно остановить и продолжить.

### 5. Результаты

После завершения на сервере:

```bash
# Файлы
/home/faizov/projects/NEFTECODE2026/
├── best_base_model.pkl              # Лучшая модель
├── base_model_search_results.json   # Все результаты
├── checkpoint_iter_*.json           # Промежуточные checkpoint'ы
└── training.log                     # Полный лог
```

### 6. Скачивание результатов

```bash
# С локальной машины
cd /Users/falexsun/code/Нефтекод/project/models

# Скачать лучшую модель
scp faizov@37.75.249.204:/home/faizov/projects/NEFTECODE2026/best_base_model.pkl ./base_model_a100.pkl

# Скачать результаты
scp faizov@37.75.249.204:/home/faizov/projects/NEFTECODE2026/base_model_search_results.json ./

# Скачать логи
scp faizov@37.75.249.204:/home/faizov/projects/NEFTECODE2026/training.log ./
```

---

## PHASE 2: Инкрементальное обучение

### Концепция

**Проблема**: Модель обучена на исторических данных, но процесс меняется → дрейф.

**Решение**: Дообучение при поступлении новых LIMS результатов.

**Workflow**:
1. Оператор отбирает пробу → отправляет в лабораторию
2. Лаборатория анализирует → результат готов через 2-24 часа
3. LIMS система публикует результат в Redis
4. Incremental Learner детектирует новые данные
5. Находит соответствующие process features (по timestamp)
6. Дообучает модель (warm start)
7. Валидирует улучшение
8. Если лучше → hot-swap новой модели

### 1. Setup Redis

```bash
# Локально (Docker)
docker run -d -p 6379:6379 redis:7-alpine

# Или на сервере
sudo apt install redis-server
sudo systemctl start redis
```

### 2. Симуляция LIMS данных

```python
import redis
import json
from datetime import datetime

# Подключение
r = redis.Redis(host='localhost', port=6379)

# Симуляция новых LIMS результатов
new_lims = [
    {
        'timestamp': '2024-01-15 10:30:00',
        'sample_id': 'S12345',
        'sulfur_ppm': 8.5,
        'density': 0.835,
        'flash_point': 67.0
    },
    {
        'timestamp': '2024-01-15 14:45:00',
        'sample_id': 'S12346',
        'sulfur_ppm': 9.2,
        'density': 0.838,
        'flash_point': 65.0
    }
]

# Публикуем в Redis
r.set('lims:new_data', json.dumps(new_lims))

print("✓ LIMS data published to Redis")
```

### 3. Запуск Incremental Learner

#### Режим 1: Continuous (daemon)

```bash
cd /Users/falexsun/code/Нефтекод/project

# Запуск в фоне
nohup uv run python src/training/incremental_learner.py \
  --base-model models/base_model_a100.pkl \
  --features ../data/features_with_timestamps.parquet \
  --mode continuous \
  --interval 60 \
  --redis-host localhost \
  > incremental_learning.log 2>&1 &

# Проверка
tail -f incremental_learning.log
```

#### Режим 2: On-demand (по триггеру)

```bash
# Однократный запуск (например, из cron или webhook)
uv run python src/training/incremental_learner.py \
  --base-model models/base_model_a100.pkl \
  --features ../data/features_with_timestamps.parquet \
  --mode once \
  --redis-host localhost
```

### 4. Интеграция с LIMS системой

**Вариант A: Push от LIMS**

```python
# В LIMS системе после завершения анализа
import requests

webhook_url = "http://your-server/api/lims/new_result"

result = {
    'timestamp': analysis_complete_time,
    'sample_id': sample.id,
    'sulfur_ppm': sulfur_result,
    'density': density_result
}

requests.post(webhook_url, json=result)
```

**Вариант B: Poll от Incremental Learner**

```python
# Learner периодически проверяет LIMS API
import requests

def check_lims_api():
    response = requests.get("http://lims-server/api/results/new")
    return response.json()
```

**Вариант C: Redis pub/sub (рекомендуется)**

```python
# LIMS публикует
r.publish('lims:new_results', json.dumps(result))

# Learner подписывается
pubsub = r.pubsub()
pubsub.subscribe('lims:new_results')

for message in pubsub.listen():
    if message['type'] == 'message':
        process_new_lims_data(message['data'])
```

### 5. Параметры дообучения

```python
# В incremental_learner.py

# Минимальное улучшение для обновления модели
IMPROVEMENT_THRESHOLD = 0.02  # 2%

# Количество итераций дообучения
INCREMENTAL_ITERATIONS = 100  # Быстро, т.к. warm start

# Минимальное кол-во новых семплов
MIN_SAMPLES = 10

# Сохранение checkpoint каждые N обновлений
CHECKPOINT_FREQUENCY = 5
```

### 6. Мониторинг

```python
# Проверка истории обучения
import pickle

with open('model_checkpoint_20260109_143000.pkl', 'rb') as f:
    data = pickle.load(f)

history = data['training_history']

for entry in history:
    print(f"Timestamp: {entry['timestamp']}")
    print(f"  MAE: {entry['metrics']['mae']:.2f}")
    print(f"  Improvement: {entry['improvement']*100:.2f}%")
```

---

## Production Setup

### Docker Compose

```yaml
version: '3.8'

services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data

  incremental-learner:
    build: .
    depends_on:
      - redis
    volumes:
      - ./models:/app/models
      - ./data:/app/data
    environment:
      - REDIS_HOST=redis
      - BASE_MODEL_PATH=/app/models/base_model_a100.pkl
    command: python src/training/incremental_learner.py --mode continuous

volumes:
  redis-data:
```

### Systemd Service

```ini
# /etc/systemd/system/incremental-learner.service

[Unit]
Description=Incremental Learning Service
After=network.target redis.service

[Service]
Type=simple
User=neftekod
WorkingDirectory=/opt/neftekod
ExecStart=/opt/neftekod/venv/bin/python \
  src/training/incremental_learner.py \
  --base-model models/base_model_a100.pkl \
  --features data/features.parquet \
  --mode continuous \
  --interval 60
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable incremental-learner
sudo systemctl start incremental-learner
sudo systemctl status incremental-learner
```

---

## Преимущества подхода

### Базовая модель на A100

✅ **200+ конфигураций** протестировано  
✅ **Лучшая архитектура** выбрана data-driven  
✅ **Быстро**: 20-40 минут на все  
✅ **Checkpoint'ы**: можно остановить и продолжить  
✅ **Reproducible**: все параметры логируются  

### Инкрементальное обучение

✅ **Адаптация к дрейфу** процесса  
✅ **Warm start**: быстрое дообучение (~100 iter)  
✅ **Валидация**: обновление только если улучшение  
✅ **История**: полный audit trail  
✅ **No downtime**: hot-swap моделей  
✅ **Trigger от LIMS**: обучение на свежих данных  

---

## Метрики и KPI

### Базовая модель

| Метрика | Target |
|---------|--------|
| Validation MAE | < 800 |
| R² | > 0.92 |
| Training time | < 50 min (200 models) |
| Best config found | Top 5% grid |

### Инкрементальное обучение

| Метрика | Target |
|---------|--------|
| Improvement threshold | 2% |
| Update frequency | По мере LIMS данных |
| Incremental training time | < 30 sec |
| Checkpoint frequency | Каждые 5 обновлений |

---

## Troubleshooting

### На A100 сервере

**GPU не используется**:
```bash
# Проверка CUDA
nvidia-smi
python3 -c "import torch; print(torch.cuda.is_available())"

# Для CatBoost
pip install catboost --upgrade

# Проверка в коде
python3 -c "from catboost import CatBoostRegressor; print(CatBoostRegressor().get_params())"
```

**Out of memory**:
```python
# Уменьшить batch size или глубину
params['max_depth'] = 6  # вместо 10
```

### Incremental Learning

**Redis connection failed**:
```bash
# Проверка Redis
redis-cli ping  # Должно вернуть PONG

# Проверка из Python
python3 -c "import redis; r=redis.Redis(); print(r.ping())"
```

**Модель не обновляется**:
```python
# Проверить threshold
IMPROVEMENT_THRESHOLD = 0.01  # Снизить до 1%

# Проверить логи
tail -f incremental_learning.log | grep "Improvement"
```

---

## Следующие шаги

1. **Запустить на A100**: `./deploy_to_a100.sh`
2. **Мониторить**: `ssh faizov@37.75.249.204 'tail -f /home/faizov/projects/NEFTECODE2026/training.log'`
3. **Скачать базовую модель** когда завершится
4. **Setup Redis** локально/на сервере
5. **Запустить Incremental Learner** в continuous mode
6. **Интегрировать с LIMS** через Redis/webhook

---

**Всё готово для production! 🚀**
