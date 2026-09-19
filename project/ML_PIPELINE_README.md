# Production ML Pipeline для Нефтекод

**Готовая система MLOps с AutoML, MLflow tracking и hot-swap моделей**

## 🚀 Быстрый старт

### 1. Запуск MLflow

```bash
# Из директории project/
docker-compose -f docker-compose-ml.yml up -d

# Проверка
curl http://localhost:5000/health
```

MLflow UI: http://localhost:5000

### 2. Обучение моделей на GPU

```bash
# Полный AutoML с 50 моделями (CatBoost, LightGBM, XGBoost)
cd project
uv run python scripts/train_production_models.py \
  --n-models 50 \
  --experiment neftekod_hackathon \
  --auto-deploy

# Быстрый прогон (10 моделей)
uv run python scripts/train_production_models.py --n-models 10

# С кастомными параметрами
uv run python scripts/train_production_models.py \
  --data-dir ../data \
  --n-models 100 \
  --mlflow-uri http://localhost:5000 \
  --auto-deploy
```

### 3. Hot-swap моделей (без перезапуска)

```python
from src.training.hotswap_manager import HotSwapModelManager

# Инициализация
manager = HotSwapModelManager(mlflow_uri='http://localhost:5000')

# Загрузка champion
manager.load_champion(run_id='abc123...')

# Загрузка challenger для A/B теста
manager.load_challenger(run_id='def456...')

# Предикция
predictions = manager.predict(X)

# Сравнение на тестовых данных
comparison = manager.compare_models(X_test, y_test)
print(comparison)
# {'champion': {'mae': 0.45, 'rmse': 0.67, 'r2': 0.89},
#  'challenger': {'mae': 0.42, 'rmse': 0.63, 'r2': 0.91}}

# Промоушн если challenger лучше
if comparison['challenger']['mae'] < comparison['champion']['mae']:
    manager.promote_challenger_to_champion()
```

## 📊 Что обучается

### AutoML Grid Search

**CatBoost** (GPU-accelerated):
- Depth: [4, 6, 8]
- Learning rate: [0.01, 0.05, 0.1]
- L2 regularization: [1, 3, 5]
- **27 комбинаций**

**LightGBM** (GPU):
- Num leaves: [15, 31, 63]
- Learning rate: [0.01, 0.05, 0.1]
- Max depth: [4, 6, 8]
- **27 комбинаций**

**XGBoost** (GPU):
- Max depth: [4, 6, 8]
- Learning rate: [0.01, 0.05, 0.1]
- Gamma: [0, 0.1, 0.5]
- **27 комбинаций**

**Итого**: 81 модель в full grid search

### Feature Engineering

1. **Лаговые признаки**: 1, 6, 12, 24 периода (10 мин - 4 часа)
2. **Rolling статистики**: mean, std, min, max (окна 1-4 часа)
3. **Временные признаки**: hour, day_of_week, month, quarter, is_weekend
4. **Разности**: diff_1, diff_6 (скорость изменения)
5. **Логарифмы**: log1p для положительных признаков
6. **Scaling**: Standard, Robust, PowerTransform

### Preprocessing варианты

- `standard`: StandardScaler
- `robust`: RobustScaler (устойчив к выбросам)
- `power`: PowerTransformer (нормализация Yeo-Johnson)
- `log`: Log1p + StandardScaler

## 📈 MLflow Tracking

Все эксперименты автоматически логируются:

- **Parameters**: model_type, hyperparameters, preprocessing
- **Metrics**: MAE, RMSE, R², MAPE (train + validation)
- **Artifacts**: 
  - Trained model + scaler
  - Feature importances
  - Config dict
- **Tags**: run metadata

### Просмотр в UI

```bash
# UI уже запущен на порту 5000
open http://localhost:5000
```

### Программный доступ

```python
import mlflow

# Получить лучший run
experiment = mlflow.get_experiment_by_name('neftekod_hackathon')
runs = mlflow.search_runs(
    experiment_ids=[experiment.experiment_id],
    order_by=['metrics.val_mae ASC'],
    max_results=1
)
best_run_id = runs.iloc[0]['run_id']
print(f"Best run: {best_run_id}, MAE: {runs.iloc[0]['metrics.val_mae']}")

# Загрузить модель
model = mlflow.sklearn.load_model(f'runs:/{best_run_id}/model')
```

## 🔄 Hot-Swap Architecture

### Champion/Challenger Pattern

```
┌─────────────────┐
│   Champion      │ ← Production traffic
│   (Current)     │
└────────┬────────┘
         │
         │ Compare metrics
         │
┌────────▼────────┐
│   Challenger    │ ← Shadow mode / A/B test
│   (Candidate)   │
└─────────────────┘
         │
         │ Promote if better
         ▼
┌─────────────────┐
│ New Champion    │
└─────────────────┘
```

### Atomic Swap (без downtime)

```python
# Thread-safe атомарная замена
with manager._lock:
    old_champion = manager._champion
    manager._champion = manager._challenger
    manager._challenger = None
    # В этой точке никогда не бывает "пустого" champion
```

### Auto-Promotion

```python
from src.training.hotswap_manager import AutoPromoter

promoter = AutoPromoter(manager, {
    'min_observations': 1000,
    'window_size': 500,
    'improvement_threshold': 0.05  # 5% лучше
})

# В production loop
for batch in production_stream:
    X, y_true = batch
    promoter.observe(X, y_true)
    
    if promoter.auto_promote_if_ready():
        print("✓ Auto-promoted challenger to champion!")
```

## 🏗️ Архитектура

```
┌─────────────┐
│   Data      │
│   (AVT +    │
│   24-2000)  │
└──────┬──────┘
       │
       ▼
┌─────────────────────────────┐
│  Feature Engineering        │
│  - Lags, rolling, diffs     │
│  - Time features            │
│  - Log transforms           │
│  - Scaling                  │
└──────┬──────────────────────┘
       │
       ▼
┌─────────────────────────────┐
│  AutoML Trainer             │
│  - Grid search              │
│  - GPU acceleration         │
│  - Cross-validation         │
└──────┬──────────────────────┘
       │
       ▼
┌─────────────────────────────┐
│  MLflow Registry            │
│  - Experiment tracking      │
│  - Model versioning         │
│  - Artifact storage         │
└──────┬──────────────────────┘
       │
       ▼
┌─────────────────────────────┐
│  Hot-Swap Manager           │
│  - Champion/Challenger      │
│  - A/B testing              │
│  - Auto-promotion           │
└──────┬──────────────────────┘
       │
       ▼
┌─────────────────────────────┐
│  Production Inference       │
│  - Real-time predictions    │
│  - Shadow mode              │
│  - Rollback support         │
└─────────────────────────────┘
```

## 📦 Созданные файлы

```
project/
├── src/training/
│   ├── automl_trainer.py        # AutoML с grid search
│   ├── hotswap_manager.py       # Hot-swap система
│   └── __init__.py
├── scripts/
│   └── train_production_models.py  # Production pipeline
├── docker-compose-ml.yml        # MLflow + Redis
└── ML_PIPELINE_README.md        # Эта документация
```

## 🎯 Метрики качества

Логируются для train и validation:

- **MAE** (Mean Absolute Error): основная метрика
- **RMSE** (Root Mean Squared Error): чувствительна к выбросам
- **R²** (R-squared): доля объясненной вариации
- **MAPE** (Mean Absolute Percentage Error): относительная ошибка

## 💡 Best Practices

### 1. Time Series Split
```python
# ПРАВИЛЬНО: сохраняем временной порядок
from sklearn.model_selection import TimeSeriesSplit
tscv = TimeSeriesSplit(n_splits=5)

# НЕПРАВИЛЬНО: random split ломает временную зависимость
from sklearn.model_selection import train_test_split  # ❌
```

### 2. Feature Scaling
```python
# ПРАВИЛЬНО: fit на train, transform на val/test
scaler.fit(X_train)
X_train_scaled = scaler.transform(X_train)
X_val_scaled = scaler.transform(X_val)

# НЕПРАВИЛЬНО: fit на val (data leakage)
scaler.fit(X_val)  # ❌
```

### 3. Model Comparison
```python
# Сравниваем только на одном hold-out set
comparison = manager.compare_models(X_test, y_test)

# Не подглядываем в test set во время обучения ❌
```

### 4. Production Deployment
```python
# ПРАВИЛЬНО: сначала challenger, потом champion
manager.load_challenger(new_run_id)
if manager.compare_models(X_test, y_test)['challenger']['mae'] < threshold:
    manager.promote_challenger_to_champion()

# НЕПРАВИЛЬНО: сразу в champion без валидации ❌
```

## 🔧 Troubleshooting

### GPU не используется

```bash
# Проверка CUDA
nvidia-smi

# Для CatBoost
pip install catboost --upgrade

# Для LightGBM
pip install lightgbm --install-option=--gpu

# Для XGBoost
pip install xgboost
```

### MLflow connection error

```bash
# Проверка контейнера
docker ps | grep mlflow

# Перезапуск
docker-compose -f docker-compose-ml.yml restart mlflow

# Проверка логов
docker logs neftekod-mlflow
```

### Out of memory

```python
# Уменьшить количество моделей
python scripts/train_production_models.py --n-models 20

# Или уменьшить iterations
config.params['iterations'] = 500  # вместо 1000
```

## 📊 Ожидаемые результаты

После запуска вы получите:

1. **50+ обученных моделей** в MLflow
2. **Топ-5 лучших** по val_mae
3. **Feature importances** для интерпретации
4. **Ready-to-deploy champion** модель
5. **Метрики**: MAE ~0.3-0.5 (зависит от target)

## 🚀 Для хакатона

```bash
# 1. Запуск MLflow (фон)
docker-compose -f docker-compose-ml.yml up -d

# 2. Быстрое обучение (10 мин на GPU)
uv run python scripts/train_production_models.py \
  --n-models 30 \
  --auto-deploy

# 3. Смотрим результаты
open http://localhost:5000

# 4. Используем best model
python
>>> from src.training.hotswap_manager import HotSwapModelManager
>>> manager = HotSwapModelManager()
>>> # run_id из вывода скрипта
>>> manager.load_champion(run_id='...')
>>> predictions = manager.predict(X)
```

## 📝 Лицензия

MIT - для хакатона и production использования

---

**Создано для Нефтекод Hackathon 2026**  
**GPU-ready | MLflow-integrated | Production-grade**
