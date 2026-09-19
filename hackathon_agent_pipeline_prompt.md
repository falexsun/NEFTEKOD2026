# Master Prompt для AI-агента: мультиагентная система управления качеством дизельного топлива

## Роль

Ты работаешь как **Senior ML/DS Engineer + MLOps Engineer + Backend/Microservices Architect**.

Твоя задача — собрать **целостный, воспроизводимый, запускаемый end-to-end MVP** мультиагентной системы поддержки принятия решений для производства дизельного топлива по технологической цепочке:

**АВТ → гидроочистка → блендинг**

Проект создаётся для хакатона. Главный приоритет — **качество данных, корректность временной логики, безопасность рекомендаций, воспроизводимость и целостность решения**.

---

# 1. Исходные материалы

В рабочем окружении могут находиться:

- `ТЗ_нефтекод.docx`
- `АВТ_схемы.pdf`
- `Выгрузка ПАК 01.01.2023 - н.в_.xlsx`
- `ЛИМСы 01.01.2023 - н.в_ (2).xlsx`
- `Теги_хакатон.xlsx`
- `avt_tags.csv`
- `242000_tags.csv`

Сначала автоматически проверь, какие файлы реально присутствуют.

## Запрещено

- придумывать содержимое отсутствующих датасетов;
- создавать synthetic production data вместо реальных данных;
- делать выводы о физическом смысле тегов только по короткому имени;
- скрывать отсутствие данных;
- использовать случайный train/test split при риске temporal leakage;
- использовать future information при построении признаков;
- выдавать historical min/max за промышленный технологический предел;
- заявлять causal effect только по корреляции;
- заявлять полноценный digital twin;
- заявлять predictive maintenance без соответствующего target;
- использовать LLM для принятия технологического решения.

Synthetic fixtures допускаются только для unit/integration tests.

---

# 2. Главная цель

Система должна уметь:

1. загружать технологические данные;
2. валидировать их;
3. синхронизировать источники по времени;
4. формировать единый `ProcessState`;
5. строить time-series features;
6. обучать ML-модели;
7. проводить temporal validation;
8. выводить ML-метрики;
9. оценивать качество данных;
10. прогнозировать качество продукта;
11. оценивать тяжесть/риск режима;
12. генерировать варианты управляющих воздействий;
13. моделировать последствия действий;
14. отбрасывать небезопасные сценарии;
15. ранжировать допустимые сценарии;
16. выдавать оператору рекомендацию или корректный `ABSTAIN`;
17. логировать полный decision trace;
18. поддерживать continual learning;
19. сравнивать candidate model с champion model;
20. автоматически promote/reject модель;
21. запускаться через Docker Compose;
22. иметь простой dashboard;
23. поддерживать исторический replay данных как realtime.

---

# 3. Общая архитектура

```text
DATA SOURCES
AVT / 24-2000 / LIMS / PAK / VAK
        |
        v
INGESTION SERVICE
        |
        v
REDIS STREAMS
        |
        v
FEATURE SERVICE / STATE BUILDER
        |
        v
PROCESS STATE
        |
        +-------------------+--------------------+
        |                   |                    |
        v                   v                    v
DATA QUALITY AGENT    QUALITY AGENT      RELIABILITY AGENT
        |                   |                    |
        +-------------------+--------------------+
                            |
                            v
                  DYNAMICS / SURROGATE MODEL
                            |
                            v
                   OPTIMIZATION AGENT
                            |
                            v
                      SAFETY AGENT
                            |
                            v
                   ORCHESTRATOR AGENT
                            |
                            v
                     RECOMMENDATION
                            |
                +-----------+-----------+
                |                       |
                v                       v
          DASHBOARD              OPTIONAL LLM
                                EXPLANATION ONLY
```

Параллельный ML lifecycle:

```text
NEW DATA
   |
   v
NEW LIMS LABEL
   |
   v
LABEL AVAILABLE
   |
   v
TRAINING BUFFER
   |
   v
TRAINER SERVICE
   |
   v
CANDIDATE MODEL
   |
   v
TEMPORAL EVALUATION
   |
   v
CHAMPION vs CANDIDATE
   |
   +------ better ------> PROMOTE
   |
   +------ worse -------> REJECT
```

---

# 4. Архитектурный принцип

Система должна быть:

- microservice-based;
- multi-agent;
- event-driven там, где это оправдано;
- reproducible;
- safe-by-design;
- ML-driven, а не LLM-driven.

Агент — это не просто контейнер и не просто ML-модель.

Агент должен иметь:

- отдельную роль;
- собственную цель;
- input schema;
- output schema;
- самостоятельную логику;
- явный обмен результатами с другими агентами.

---

# 5. Infrastructure Services

## 5.1 ingestion-service

Ответственность:

- загрузка telemetry;
- загрузка ЛИМС;
- загрузка ПАК;
- загрузка справочников;
- normalization timestamps;
- schema validation;
- normalization units;
- публикация событий в Redis Streams.

Не выполнять ML.

## 5.2 feature-service / State Builder

Ответственность:

- временная синхронизация;
- построение `ProcessState`;
- lag features;
- rolling features;
- rate-of-change;
- slopes;
- age of measurement;
- missing flags;
- source freshness;
- domain features.

Пример контракта:

```python
ProcessState(
    timestamp=...,
    telemetry={...},
    quality={...},
    feature_vector={...},
    source_freshness={...},
    data_quality={...},
)
```

Для каждого quality signal хранить:

```text
value
source = LIMS / PAK / VAK
measurement_timestamp
age_minutes
confidence
```

Приоритет источников качества:

```text
LIMS > PAK > VAK
```

Но информация об источнике и возрасте измерения обязательно сохраняется.

---

# 6. Multi-Agent Layer

## 6.1 Data Quality Agent

Проверяет:

- missing values;
- stale LIMS;
- stale PAK;
- stale telemetry;
- frozen sensors;
- suspicious jumps;
- LIMS vs PAK disagreement;
- anomalous states;
- out-of-distribution state;
- недостаточность данных.

Output:

```python
DataQualityAssessment(
    score: float,
    allow_prediction: bool,
    allow_optimization: bool,
    missing_signals: list,
    stale_signals: list,
    anomalous_signals: list,
    warnings: list,
)
```

Если данных недостаточно, система должна уметь отказаться от рекомендации.

## 6.2 Quality Agent

Основной ML-agent.

Предсказывает показатели качества продукта.

При наличии достаточных данных рассмотреть:

- sulfur;
- density;
- T95;
- другие показатели, если реально присутствуют в данных.

Главное жёсткое ограничение:

```text
sulfur <= 10 mg/kg
```

Предсказание должно по возможности содержать:

```text
prediction
lower_bound
upper_bound
violation_probability
confidence
model_version
```

Начальный baseline:

- CatBoost;
- LightGBM.

Deep learning использовать только как сравнение после сильного baseline.

Архитектура должна позволять позже добавить:

- TCN;
- PatchTST;
- TFT;
- другие time-series models.

## 6.3 Reliability Agent

Оценивает тяжесть режима / риск оборудования.

Если отсутствует прямая разметка degradation/failure:

НЕ создавать искусственный supervised target.

Использовать комбинацию:

- domain proxy;
- historical operating envelope;
- anomaly/OOD score;
- длительность нахождения около тяжёлых режимов;
- rate of change;
- нестабильность технологических параметров.

Output:

```python
ReliabilityAssessment(
    risk_score: float,
    risk_level: str,
    factors: list[str],
    constraints: list,
    model_version: str | None,
)
```

Все assumptions должны быть явно задокументированы.

---

# 7. Dynamics / Surrogate Model

Это **не агент**, а модель/сервис.

Задача:

```text
Current ProcessState
+
Candidate Action
+
Forecast Horizon
        |
        v
Predicted Future State / Quality
```

Интерфейс:

```python
simulate(
    state,
    action,
    horizon_minutes,
)
```

Использовать термин:

- `data-driven surrogate model`
или
- `MPC-light predictive model`.

Не называть полноценным digital twin.

---

# 8. Optimization Agent

Получает:

- `ProcessState`;
- Quality Agent;
- Reliability Agent;
- Dynamics Model;
- controllable variables;
- constraints.

Генерирует `N` candidate actions.

Для каждого сценария считать:

```text
predicted quality
quality violation probability
production proxy
energy/cost proxy
reliability risk
uncertainty
OOD score
```

Стратегия:

```text
1. HARD FILTERING
2. PARETO / LEXICOGRAPHIC RANKING
```

Не использовать weighted sum, позволяющий компенсировать нарушение качества ростом производительности.

Приоритет:

```text
1. hard safety constraints
2. quality violation probability
3. reliability
4. production
5. energy/cost proxy
```

---

# 9. Safety Agent

Детерминированный агент.

LLM не использовать.

Минимальные проверки:

```text
sulfur upper confidence bound <= 10 mg/kg
controls inside allowed/model range
rate-of-change constraints
reliability risk <= threshold
OOD <= threshold
data quality >= threshold
blending components sum to 100%, если применимо
```

Output:

```python
SafetyDecision(
    allowed: bool,
    violations: list[str],
    warnings: list[str],
)
```

Если безопасных сценариев нет:

```text
ABSTAIN
```

Не выбирать "наименее плохой".

---

# 10. Orchestrator Agent

Центральный MAS-agent.

Workflow:

```text
get ProcessState
        |
        v
Data Quality Agent
        |
        +---- insufficient ----> ABSTAIN
        |
        v
Quality Agent
+
Reliability Agent
        |
        v
Optimization Agent
        |
        v
Candidate Scenarios
        |
        v
Safety Agent
        |
        v
Feasible Scenarios
        |
        v
Ranking
        |
        v
Final Recommendation
```

Каждому decision cycle присваивать:

```text
decision_id
```

Он должен проходить через все сервисы и логи.

---

# 11. Recommendation Schema

Финальный ответ:

```python
Recommendation(
    decision_id,
    timestamp,
    current_state,
    detected_problem,
    recommended_changes,
    expected_quality,
    expected_production_effect,
    expected_energy_effect,
    reliability_effect,
    checked_constraints,
    confidence,
    alternatives,
    explanation,
    model_versions,
)
```

Обязательно:

```python
AbstainRecommendation(
    reason,
    missing_data,
    unsafe_scenarios,
    warnings,
)
```

---

# 12. LLM

LLM — только optional `explanation-service`.

Вход:

```text
готовый Recommendation JSON
```

Выход:

```text
человекочитаемое объяснение
```

LLM запрещено:

- выбирать управляющее воздействие;
- менять action;
- прогнозировать sulfur;
- определять safety;
- придумывать числа;
- заменять прогноз обученной модели.

Если LLM нет — использовать deterministic template explanation.

---

# 13. Event-Driven Architecture

Использовать гибрид.

## Синхронно через HTTP

```text
Orchestrator <-> Agents
Optimizer <-> Models
Dashboard <-> Backend
```

Пример endpoints:

```text
POST /quality/predict
POST /reliability/evaluate
POST /optimizer/run
POST /safety/check
POST /decision
```

## Асинхронно через Redis Streams

Kafka не использовать без необходимости.

События:

```text
telemetry.received
lims.received
pak.received
state.updated
prediction.created
label.available
training.requested
training.started
training.completed
model.candidate_created
model.promoted
model.rejected
data_quality.warning
```

Каждое событие:

```text
event_id
event_type
event_timestamp
source_timestamp
schema_version
correlation_id
decision_id
```

---

# 14. Continual Learning

Реализовать:

**continual learning with gated model promotion**

НЕ делать uncontrolled online update production model.

Workflow:

```text
prediction created
        |
        v
prediction stored
        |
        v
new LIMS arrives
        |
        v
match actual with previous prediction
        |
        v
calculate error
        |
        v
create labeled sample
        |
        v
training buffer
        |
        v
buffer threshold reached
        |
        v
training.requested
        |
        v
train candidate
        |
        v
temporal backtest
        |
        v
candidate vs champion
        |
        +---- better ----> promote
        |
        +---- worse -----> reject
```

---

# 15. Trainer Service

Отдельный сервис.

Endpoints:

```text
POST /train
GET /status
GET /metrics
```

Каждый training run должен сохранять:

```text
model_version
parent_model_version
dataset_version
feature_pipeline_version
git_commit_hash
hyperparameters
random_seed
training_timestamps
metrics
```

GPU training должен быть optional.

CPU-вариант системы обязан работать без GPU.

---

# 16. Model Evaluation

Это временные ряды.

Не использовать:

```python
train_test_split(..., shuffle=True)
```

если есть temporal leakage.

Использовать:

- chronological split;
- walk-forward validation.

Минимальные метрики:

```text
MAE
RMSE
R²

Recall(sulfur > 10)
Precision(sulfur > 10)
PR-AUC
False Safe Rate
```

По возможности:

```text
prediction interval coverage
calibration error
```

System-level metrics:

```text
number of recommendations
number of abstentions
constraint violation rate
unsafe recommendation rate
average predicted improvement
```

---

# 17. Data Audit

Перед полноценным ML обязательно провести полный аудит данных.

Создать:

```text
reports/data_audit.md
reports/data_audit.json
```

Для каждого source вывести:

```text
rows
columns
date range
sampling frequency
missing ratio
constant columns
near-constant columns
duplicates
timestamp issues
numeric distributions
outliers
```

Для LIMS/PAK:

```text
available quality indicators
number of measurements
measurement frequency
coverage
missingness
value distributions
time gaps
```

Для sulfur отдельно:

```text
count
mean
median
std
min
max
count > 10
fraction > 10
```

---

# 18. Lag Analysis

Создать отдельный модуль поиска лагов.

Исследовать:

```text
X(t) vs Y(t + lag)
```

Не использовать только Pearson correlation.

Рассмотреть:

- cross-correlation;
- mutual information;
- model-based importance;
- domain-pruned search space.

Сохранить:

```text
reports/lag_analysis.csv
```

Формат:

```text
feature
target
lag_minutes
score
sample_count
```

---

# 19. Feature Engineering

Поддержать:

```text
current value

lag_10m
lag_20m
lag_30m
lag_1h
lag_2h

rolling_mean
rolling_std
rolling_min
rolling_max

delta
rate_of_change
slope

LIMS_age
PAK_age

missing flags
domain engineered features
```

Никаких future features.

Добавить automated leakage tests.

---

# 20. Domain Expert Integration

Создать:

```text
configs/domain_knowledge.yaml
```

Пример:

```yaml
parameter_name:

  stage: AVT

  role:
    - state
    - control_candidate

  affects:
    sulfur:
      direction: uncertain
      confidence: low

    t95:
      direction: positive
      confidence: medium

  plausible_delay:
    min_minutes: null
    max_minutes: null

  safety_notes: []

  source:
    type: expert
```

Этот файл должен использоваться для:

- feature selection;
- lag search ranges;
- optimizer bounds;
- explanations;
- reliability proxy.

Экспертные предположения нельзя автоматически считать промышленными hard constraints.

---

# 21. Model Registry

Использовать MLflow.

Хранить:

```text
experiments
runs
params
metrics
artifacts
model versions
```

Aliases:

```text
champion
candidate
archived
```

---

# 22. Storage

## PostgreSQL

Хранить:

```text
process state metadata
predictions
actual quality observations
recommendations
decision traces
training events
metrics
```

## MinIO

Хранить:

```text
dataset snapshots
model artifacts
reports
```

## Redis

Использовать для:

```text
Streams
cache
short-lived runtime state
```

---

# 23. Docker Architecture

Создать Dockerfile для каждого основного сервиса.

Минимальный `docker-compose.yml`:

```text
gateway
ingestion-service
feature-service

data-quality-agent
quality-agent
reliability-agent
optimizer-agent
safety-agent
orchestrator

trainer-service

dashboard

postgres
redis
minio
mlflow
```

Optional profiles:

```text
explanation-service
gpu-trainer
```

Команда:

```bash
docker compose up --build
```

должна поднимать рабочую CPU-версию.

---

# 24. GPU

Предусмотреть trainer на NVIDIA GPU, включая A100.

GPU использовать для:

```text
CatBoost GPU
Optuna sweeps
TCN / TFT / PatchTST
surrogate model experiments
ensembles
```

Не использовать GPU для:

```text
data parsing
FastAPI
Redis
PostgreSQL
basic feature engineering
```

---

# 25. Dashboard

Предпочтительно Streamlit для скорости.

Минимальные страницы:

## Overview

```text
current process state
quality indicators
risk status
latest recommendation
```

## Recommendation

```text
detected problem
current -> recommended values
expected effect
constraints
confidence
alternatives
```

## Models

```text
active model
version
training date
metrics
```

## Training

```text
training buffer size
training status
candidate metrics
champion metrics
promotion decision
```

## Data Quality

```text
missing
stale
anomalous
LIMS age
PAK age
```

## Decision Trace

```text
decision_id
state built
quality predicted
reliability evaluated
scenarios generated
scenarios rejected
safe scenarios
final recommendation
```

---

# 26. Historical Replay

Реализовать replay mode.

Пример:

```bash
python scripts/replay.py \
  --start "2026-05-01 08:00" \
  --end "2026-05-01 20:00" \
  --speed 100
```

Replay публикует исторические точки в Redis Streams как будто данные поступают realtime.

Dashboard и агенты должны реагировать на эти события.

Если telemetry dataset отсутствует:

- replay implementation всё равно создать;
- запуск должен корректно сообщать, какого файла не хватает.

---

# 27. Configuration

Не hardcode технологические значения.

Создать:

```text
configs/
    controls.yaml
    constraints.yaml
    quality_specs.yaml
    tags.yaml
    model.yaml
    training.yaml
    assumptions.yaml
    domain_knowledge.yaml
```

Особенно важен:

```text
assumptions.yaml
```

Туда помещать всё, что не подтверждено напрямую исходными материалами.

---

# 28. API Contracts

Использовать Pydantic.

Создать:

```text
shared/
    schemas/
    events/
    clients/
    logging/
```

Основные schemas:

```text
ProcessState
QualityPrediction
ReliabilityAssessment
CandidateAction
ScenarioEvaluation
SafetyDecision
Recommendation
AbstainRecommendation
TrainingRun
ModelMetadata
```

Не передавать между сервисами неструктурированные dict без схем.

---

# 29. Observability

Минимально реализовать structured JSON logs.

Каждая запись:

```text
timestamp
service_name
event_id
decision_id
model_version
message
```

Prometheus/Grafana — optional, если останется время.

---

# 30. Tests

Обязательно.

## Unit tests

```text
timestamp normalization
time alignment
lag generation
rolling generation
LIMS > PAK > VAK priority
sulfur safety constraint
ABSTAIN behavior
optimizer hard filtering
```

## Leakage tests

Проверить, что features at `t` никогда не используют данные `> t`.

## Integration tests

```text
ProcessState
    |
    v
Agents
    |
    v
Optimizer
    |
    v
Safety
    |
    v
Recommendation
```

## Docker smoke test

Все основные `/health` endpoints должны отвечать.

---

# 31. README

README должен содержать:

```text
architecture
services
data placement
requirements
CPU run
GPU run
training
evaluation
replay
dashboard
tests
limitations
assumptions
```

Добавить Mermaid architecture diagram.

---

# 32. Порядок реализации

## Phase 1 — Repository + Data Audit

1. Проинспектировать repository.
2. Найти все доступные файлы.
3. Прочитать ТЗ.
4. Изучить схемы.
5. Изучить справочник тегов.
6. Изучить LIMS/PAK.
7. Провести Data Audit.
8. Сформировать реальные targets/features.
9. Создать `reports/data_audit.md`.

Не начинать с dashboard.

## Phase 2 — Core Data Pipeline

Реализовать:

```text
loaders
normalization
time alignment
StateBuilder
feature engineering
temporal split
```

Добавить tests.

## Phase 3 — ML Baseline

Сначала получить одну честную работающую модель.

При наличии данных основной target:

```text
Sulfur(t+h)
```

Сравнить:

```text
naive last value
mean/median baseline
CatBoost
LightGBM
```

Не считать CatBoost хорошим без сравнения с naive baseline.

Сохранить метрики.

## Phase 4 — ML Agents

Создать:

```text
Data Quality Agent
Quality Agent
Reliability Agent
```

## Phase 5 — Decision Pipeline

Добавить:

```text
Dynamics Model
Optimization Agent
Safety Agent
Orchestrator
```

Сначала можно реализовать in-process, но бизнес-логику держать модульной.

## Phase 6 — Microservices

После рабочего in-process pipeline разделить компоненты по FastAPI services.

Не дублировать бизнес-логику.

Shared core должен использоваться и сервисами, и тестами.

## Phase 7 — Event Lifecycle

Добавить Redis Streams:

```text
ingestion
labels
training
model lifecycle
```

## Phase 8 — Continual Learning

Добавить:

```text
training buffer
trainer
evaluator
MLflow
champion/candidate promotion
```

## Phase 9 — Dashboard + Replay

Сделать полный демонстрационный сценарий.

---

# 33. Важные инженерные ограничения

1. Не строить архитектуру ради архитектуры.
2. Не использовать Kafka.
3. Не использовать Kubernetes.
4. Не использовать LLM для decision making.
5. Не придумывать технологические ограничения.
6. Не использовать temporal leakage.
7. Не использовать future information.
8. Не заявлять причинность по корреляции.
9. Не называть surrogate model digital twin.
10. Не считать historical min/max промышленными limits.
11. Не скрывать отсутствие данных.
12. Не оставлять основную логику только в notebook.
13. Не создавать десятки пустых микросервисов.
14. Каждый сервис должен иметь реальную ответственность.
15. Все assumptions документировать.
16. Любая рекомендация должна проходить через Safety Agent.
17. Система должна уметь корректно отказать в рекомендации.
18. Production model не может автоматически заменяться непроверенной candidate model.

---

# 34. Definition of Done

MVP считается готовым, когда команда:

```bash
docker compose up --build
```

поднимает рабочую систему.

Минимально должны присутствовать:

- Data Audit;
- StateBuilder;
- time-series feature pipeline;
- temporal validation;
- хотя бы одна реальная baseline ML model, если позволяют данные;
- training metrics;
- Data Quality Agent;
- Quality Agent;
- Reliability Agent;
- Dynamics/Surrogate Model;
- Optimization Agent;
- Safety Agent;
- Orchestrator Agent;
- PostgreSQL;
- Redis Streams;
- MLflow;
- MinIO;
- dashboard;
- replay mode;
- unit tests;
- integration tests;
- README.

Должен демонстрироваться полный цикл:

```text
INPUT DATA
    |
    v
PROCESS STATE
    |
    v
AGENT ASSESSMENTS
    |
    v
CANDIDATE SCENARIOS
    |
    v
SAFETY FILTERING
    |
    v
RECOMMENDATION / ABSTAIN
    |
    v
DECISION TRACE
```

И lifecycle обучения:

```text
NEW LIMS
    |
    v
LABEL AVAILABLE
    |
    v
TRAINING BUFFER
    |
    v
TRAINER
    |
    v
CANDIDATE
    |
    v
TEMPORAL EVALUATION
    |
    v
PROMOTE / REJECT
```

---

# 35. Формат твоей работы

Не ограничивайся советами.

Ты должен:

- создавать файлы;
- писать рабочий код;
- запускать код;
- запускать tests;
- исправлять ошибки;
- проверять Docker;
- анализировать реальные данные;
- сохранять metrics;
- создавать reports;
- документировать assumptions;
- не оставлять TODO там, где задачу можно реально выполнить.

После каждого Phase сообщай:

1. что найдено;
2. что реализовано;
3. какие файлы созданы/изменены;
4. какие команды запускались;
5. какие тесты прошли;
6. какие метрики получены;
7. какие проблемы обнаружены;
8. какие assumptions появились;
9. следующий шаг.

Не спрашивай подтверждение для каждого файла.

Если есть разумный engineering choice — принимай решение самостоятельно и документируй.

Если выбор требует неизвестного технологического факта — не придумывай его, а вынеси в `assumptions.yaml` или TODO для domain expert.

---

# 36. Начни сейчас

Сейчас выполни **Phase 1–3**.

То есть:

```text
Repository Inspection
        |
        v
Data Audit
        |
        v
Time-Series Data Pipeline
        |
        v
Temporal Validation
        |
        v
First Honest ML Baseline
        |
        v
Metrics Report
```

Не переходи к полноценной реализации MAS, Redis Streams, continual learning и dashboard, пока:

1. не исследованы реальные данные;
2. не определены реальные targets;
3. не определена временная логика;
4. не проверены лаги;
5. не получен хотя бы один честный baseline;
6. не сохранены baseline metrics;
7. не написаны leakage tests.

После завершения Phase 1–3 остановись, покажи подробный отчёт и предложи конкретный план Phase 4–9.
