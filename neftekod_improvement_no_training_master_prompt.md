# MASTER PROMPT: улучшение NEFTEKOD2026 без обучения и дообучения моделей

Ты работаешь как:

- Senior ML Engineer
- MLOps Engineer
- Backend/Microservices Architect
- Senior Python Engineer
- Code Reviewer

Репозиторий:

https://github.com/falexsun/NEFTEKOD2026

Основная рабочая ветка:

`dev`

Проект — мультиагентная система поддержки принятия решений для производства дизельного топлива:

**АВТ → гидроочистка → блендинг**

Текущий проект уже имеет MVP-каркас. Его **НЕ нужно переписывать с нуля**.

Твоя задача — улучшить архитектуру, runtime, микросервисы, качество кода, безопасность, работу с данными, event-driven слой, observability и интеграцию существующих компонентов.

---

# 0. КРИТИЧЕСКОЕ ОГРАНИЧЕНИЕ

На текущем этапе **ЗАПРЕЩЕНО обучать, переобучать или дообучать ML-модели**.

Не запускать:

- `.fit()`
- `partial_fit()`
- fine-tuning
- hyperparameter search
- Optuna
- CatBoost training
- LightGBM training
- XGBoost training
- neural network training
- continual learning
- candidate/champion retraining
- model promotion по новым метрикам

Не изменять существующие model artifacts без необходимости.

Не удалять существующие модели.

Не пытаться улучшить ML-метрики за счёт нового обучения.

Если для проверки логики нужен inference — можно использовать **уже существующие сохранённые модели**, но нельзя их обучать заново.

Если существующая модель не может быть корректно вызвана — исправить инфраструктуру/схему inference, не переобучая модель.

---

# 1. ГЛАВНАЯ ЦЕЛЬ ЭТОГО ЭТАПА

На текущем этапе нужно улучшить:

1. структуру runtime
2. интеграцию уже существующих моделей
3. feature schema
4. ProcessState
5. Data Quality Agent
6. Reliability Agent
7. Optimization Agent
8. Safety Agent
9. Orchestrator Agent
10. микросервисную архитектуру
11. Docker Compose
12. Redis Streams
13. API contracts
14. error handling
15. observability
16. Prometheus
17. Grafana
18. runtime dashboard
19. replay mode
20. tests
21. документацию

Но **НЕ ML training pipeline**.

---

# 2. СНАЧАЛА ПРОВЕДИ ТЕХНИЧЕСКИЙ АУДИТ

Перед изменениями:

1. прочитай README
2. изучи `docker-compose.yml`
3. изучи `Dockerfile`
4. изучи `configs/*`
5. изучи `src/ingestion/*`
6. изучи `src/feature_service/*`
7. изучи `src/training/*`
8. изучи `src/agents/*`
9. изучи `src/api/*`
10. изучи `src/dashboard/*`
11. изучи `tests/*`
12. изучи `reports/*`
13. изучи существующие модели в `models/`
14. проверь, какие сервисы реально запускаются
15. проверь, какие части README соответствуют реальному коду

Создай:

`reports/technical_audit_runtime.md`

Разделы:

- реализовано
- частично реализовано
- placeholder
- отсутствует
- потенциальные runtime ошибки
- потенциальные safety проблемы
- проблемы микросервисной архитектуры
- проблемы Docker
- проблемы Redis
- проблемы API
- проблемы inference wiring
- проблемы observability

---

# 3. НЕ ПЕРЕОБУЧАТЬ МОДЕЛИ, НО ИСПРАВИТЬ INFERENCE

Существующие модели можно использовать только в режиме inference.

Нужно убедиться, что:

```text
existing model artifact
        ↓
correct feature schema
        ↓
correct feature order
        ↓
inference
        ↓
Quality Agent
```

Запрещено использовать:

```python
sorted(feature_vector.keys())
```

если модель обучалась в другом порядке колонок.

Создать metadata-слой:

```python
ModelArtifactMetadata(
    model_name,
    model_version,
    target,
    prediction_horizon_minutes,
    feature_names,
    feature_pipeline_version,
)
```

Если feature names нельзя восстановить надёжно из существующих artifacts:

- не придумывать их
- явно зафиксировать limitation
- при несовпадении schema делать `ABSTAIN`, а не fake prediction

Добавить тест:

```text
load existing model
→ prepare feature vector
→ verify schema
→ inference or explicit controlled failure
```

---

# 4. УБРАТЬ MAGIC FALLBACKS

В decision path нельзя использовать значения вроде:

```python
predicted_sulfur = 7.0
std = 1.5
confidence = 0.5
```

как будто это реальный прогноз.

Если модель недоступна:

```text
ABSTAIN
```

Если feature schema несовместима:

```text
ABSTAIN
```

Если inference падает:

```text
ABSTAIN
```

Если uncertainty неизвестна:

```text
unknown / None
```

Не придумывать safety confidence.

---

# 5. PROCESS STATE

Сделать единый runtime-путь:

```text
raw telemetry
        ↓
ingestion
        ↓
StateBuilder
        ↓
FeatureBuilder
        ↓
ProcessState + FeatureVector
        ↓
Agents
```

Training и runtime код не должны иметь две несовместимые логики формирования features.

Даже без переобучения необходимо централизовать feature construction.

---

# 6. SOURCE FRESHNESS

Исправить реальное заполнение:

```python
SourceFreshness
```

Для:

- AVT
- 24-2000
- PAK sulfur
- PAK density
- LIMS

Поля:

```text
source_timestamp
current_timestamp
age_minutes
is_stale
```

Data Quality Agent должен использовать реальные значения.

---

# 7. QUALITY SOURCE RESOLUTION

Реализовать отдельный:

`QualitySourceResolver`

Нужно учитывать:

```text
LIMS
PAK
VAK
```

Не просто хранить строку `source`, а реализовать policy.

Создать:

`configs/quality_source_policy.yaml`

Пример:

```text
LIMS available and valid
→ high-priority source

LIMS stale, fresh PAK available
→ use configured fallback policy

PAK unavailable
→ VAK with lower confidence

all unavailable
→ ABSTAIN
```

Ничего не придумывать без явного правила в config.

Добавить unit tests.

---

# 8. DATA QUALITY AGENT

Улучшить без ML training.

Проверять:

- missing signals
- stale signals
- frozen sensors
- impossible jumps
- source conflicts
- too many missing features
- too many imputed values
- incomplete feature vector
- stale PAK
- stale LIMS
- absent sulfur source
- invalid timestamps

Отдельно:

```python
allow_prediction
allow_optimization
```

Orchestrator обязан использовать оба.

---

# 9. FROZEN SENSOR

Нельзя определять frozen sensor по одному значению.

Frozen sensor проверяется по истории:

```text
x(t-5)
x(t-4)
x(t-3)
x(t-2)
x(t-1)
x(t)
```

Использовать:

- consecutive identical values
- rolling std
- duration without change

Никакого:

```python
val == int(val)
```

---

# 10. SEMANTIC TAG REGISTRY

Не определять физический смысл по первой букве тега.

Создать semantic metadata слой.

Пример:

```yaml
u24_T11:
  semantic_name: "Расход сырья на установку"
  physical_quantity: flow
  role: state
  unit: ...

u24_F22:
  semantic_name: "Температура в сепараторе"
  physical_quantity: temperature
  role: state
  unit: ...
```

Использовать registry в:

- optimizer
- reliability
- dashboard
- explanations
- production proxy
- energy proxy

---

# 11. CONTROL REGISTRY

Убрать логику:

```text
все telemetry tags = controls
±20%
```

Использовать только:

`configs/controls.yaml`

Создать `ControlRegistry`.

Каждый control:

```text
name
semantic_name
stage
unit
role
model_range
max_step
max_rate_of_change
constraint_source
confidence
```

Optimizer может менять только:

```text
role = control_candidate
```

Если range является только предположением:

обозначить как:

```text
model_trust_region
```

а не industrial limit.

---

# 12. OPTIMIZATION AGENT

Не обучать новые модели.

На данном этапе улучшить архитектуру оптимизатора.

Обязательно:

- deterministic seed
- baseline scenario `NO CHANGE`
- только разрешённые controls
- небольшие perturbations
- model trust region
- explicit scenario schema
- reproducibility

Каждый сценарий:

```python
ScenarioEvaluation(
    scenario_id,
    action,
    predicted_quality,
    production_proxy,
    energy_proxy,
    reliability_risk,
    uncertainty,
    ood_score,
    safety_status,
)
```

Если surrogate/inference недостаточно надёжен:

не выдавать технологическую рекомендацию как уверенную.

Можно вернуть:

```text
scenario evaluation unavailable
```

и `ABSTAIN`.

---

# 13. PRODUCTION / ENERGY PROXY

Запрещено определять proxy по буквам tag name:

```python
if "F" in tag
if "T" in tag
```

Использовать semantic registry.

Если реального production/energy target нет:

называть честно:

```text
production_proxy
energy_severity_proxy
```

Не выдавать их за реальные деньги, кВт·ч или физически точный эффект.

---

# 14. RELIABILITY AGENT

Не обучать новую модель.

Улучшить rule/statistical runtime implementation.

Использовать:

- historical envelope, если он уже рассчитан/доступен
- rolling std
- rate of change
- duration near boundaries
- stale/frozen signals
- configured domain constraints

Если historical envelope отсутствует:

не придумывать.

Использовать термин:

`historical operating envelope`

а не:

`industrial safety limits`.

---

# 15. SURROGATE MODEL

Не обучать новую surrogate model на этом этапе.

Текущую реализацию привести в честное состояние.

Если реальная модель для what-if отсутствует:

не имитировать её магическими значениями.

Разрешён вариант:

```text
SurrogateService
status = unavailable
```

Тогда Optimization Agent должен корректно вернуть:

```text
ABSTAIN / simulation unavailable
```

или работать только в явно обозначенном demo-mode без claims о физической достоверности.

---

# 16. SAFETY AGENT

Safety Agent должен быть deterministic.

Fail closed.

Reject при:

```text
model unavailable
feature schema mismatch
quality prediction unavailable
data quality insufficient
control outside allowed range
control step too large
reliability risk too high
OOD too high
stale critical data
unknown critical uncertainty
```

Любая unexpected exception:

```text
REJECT / ABSTAIN
```

а не разрешение сценария.

---

# 17. ORCHESTRATOR

Workflow:

```text
ProcessState
    ↓
Data Quality Agent
    ↓
allow_prediction?
    ├─ NO → ABSTAIN
    ↓
Quality Agent
    ↓
Reliability Agent
    ↓
allow_optimization?
    ├─ NO → forecast-only / ABSTAIN
    ↓
Optimization Agent
    ↓
Safety Agent
    ↓
safe scenarios?
    ├─ NO → ABSTAIN
    ↓
Ranking
    ↓
Recommendation
```

Каждому decision cycle:

```text
decision_id
correlation_id
```

Логировать:

```text
timestamp
state id
data quality
quality model version
prediction status
reliability
candidate count
rejected count
rejection reasons
selected scenario
final status
```

---

# 18. MULTI-AGENT ARCHITECTURE

Сохранить агентов:

```text
Data Quality Agent
Quality Agent
Reliability Agent
Optimization Agent
Safety Agent
Orchestrator Agent
```

Не называть агентами:

```text
Redis
Postgres
MLflow
Trainer
Feature Service
Surrogate Model
```

---

# 19. РЕАЛЬНЫЕ МИКРОСЕРВИСЫ

Перейти от модульного монолита к реальной микросервисной архитектуре.

Разнести минимум:

```text
gateway
feature-service
quality-agent
reliability-agent
optimization-agent
safety-agent
orchestrator
dashboard
```

Trainer-service оставить выключенным/неактивным на этом этапе.

Каждый сервис:

- собственный FastAPI app
- `/health`
- `/ready`
- Pydantic schemas
- structured logs
- timeout handling
- error handling
- Docker service

---

# 20. SHARED CORE

Не копировать бизнес-логику между контейнерами.

Использовать:

```text
src/shared/
    schemas/
    events/
    clients/
    config/
    logging/
    errors/
```

---

# 21. SERVICE COMMUNICATION

Decision loop:

```text
Orchestrator
  ├─ HTTP → Data Quality Agent
  ├─ HTTP → Quality Agent
  ├─ HTTP → Reliability Agent
  ├─ HTTP → Optimization Agent
  └─ HTTP → Safety Agent
```

Использовать:

- explicit timeout
- meaningful status codes
- fail-closed behavior
- retries только там, где это безопасно

---

# 22. REDIS STREAMS

Добавить/довести event-driven слой.

Использовать для:

```text
telemetry.received
lims.received
pak.received
state.updated
prediction.created
decision.created
data_quality.warning
service.warning
```

На этом этапе **НЕ запускать события обучения/дообучения моделей**.

Можно оставить event schemas на будущее, но не активировать training consumers.

Реализовать:

- consumer groups
- ACK
- event_id
- correlation_id
- schema_version
- idempotency

---

# 23. REPLAY MODE

Исторический replay должен реально работать через Redis Streams.

```bash
python scripts/replay.py   --start "..."   --end "..."   --speed 100
```

Цепочка:

```text
historical data
    ↓
Redis Streams
    ↓
feature service
    ↓
agents
    ↓
orchestrator
    ↓
runtime dashboard
```

Проверить end-to-end.

---

# 24. POSTGRES

Хранить:

```text
process states metadata
predictions
recommendations
abstentions
decision traces
agent assessments
runtime errors
```

На текущем этапе не нужно хранить новые training runs.

Добавить reproducible schema initialization/migrations.

---

# 25. MLFLOW

Не запускать новое обучение.

MLflow можно оставить как registry/UI для существующих artifacts.

Если интеграция пока декоративная:

- либо реально подключить existing model metadata
- либо честно пометить как `prepared for future training lifecycle`

Не создавать fake training runs.

---

# 26. MINIO

Использовать только если реально нужен для:

- existing model artifacts
- reports
- snapshots

Не создавать декоративную интеграцию.

---

# 27. PROMETHEUS

Добавить monitoring.

Каждый FastAPI сервис должен отдавать `/metrics`.

Минимальные system metrics:

```text
http_requests_total
http_request_duration_seconds
http_errors_total
service_up
```

MAS/runtime metrics:

```text
decisions_total
recommendations_total
abstentions_total
unsafe_scenarios_total
safe_scenarios_total
decision_duration_seconds
data_quality_score
reliability_risk
quality_prediction_available
surrogate_available
```

Не публиковать fake ML accuracy metrics.

---

# 28. GRAFANA

Добавить Grafana.

Минимум 3 dashboard.

## System Health

```text
service status
latency
errors
request rate
```

## MAS Health

```text
decisions
recommendations
abstentions
safe scenarios
rejected scenarios
decision latency
```

## Data/Model Runtime Health

```text
data freshness
data quality score
model availability
model version
feature schema mismatch count
inference errors
```

На текущем этапе не показывать новые training metrics.

---

# 29. DOCKER COMPOSE

Финальный CPU runtime должен запускаться:

```bash
docker compose up --build
```

Минимальные services:

```text
gateway
feature-service
quality-agent
reliability-agent
optimization-agent
safety-agent
orchestrator
dashboard
redis
postgres
prometheus
grafana
```

Optional:

```text
minio
mlflow
```

Trainer не должен автоматически запускать обучение.

Если trainer существует:

перевести его в disabled profile:

```text
profile: training
```

и не запускать по умолчанию.

---

# 30. HEALTHCHECKS

Каждый сервис:

```text
/health
/ready
```

`health`:

процесс жив.

`ready`:

сервис действительно способен выполнять функцию.

Например Quality Agent:

```text
health = true
ready = model loaded + feature schema available
```

---

# 31. OBSERVABILITY

Structured JSON logs.

Каждая запись:

```text
timestamp
level
service
decision_id
correlation_id
event_id
model_version
message
```

Не логировать огромные feature vectors целиком без необходимости.

---

# 32. DASHBOARD

Streamlit dashboard должен брать runtime данные через API/Postgres, а не только static reports.

Страницы:

## Overview

```text
service health
latest process state
latest decision
latest quality status
```

## Recommendation

```text
recommendation / ABSTAIN
reason
current values
proposed values
safety status
```

## Data Quality

```text
source freshness
missing
stale
frozen
warnings
```

## Agents

```text
Data Quality Agent status
Quality Agent status
Reliability Agent status
Optimization Agent status
Safety Agent status
Orchestrator status
```

## Decision Trace

```text
decision_id
agent calls
statuses
rejected scenarios
final result
```

## System Monitoring

summary/links из Prometheus/Grafana.

Training page пока скрыть или показать:

```text
Training disabled in current runtime phase
```

---

# 33. TESTS

Усилить unit/integration tests.

Обязательно:

## Runtime

```text
Quality Agent loads existing model or returns controlled unavailable state
feature schema mismatch → ABSTAIN
missing model → ABSTAIN
```

## Data Quality

```text
fresh data → allowed
stale data → no optimization
missing critical source → controlled behavior
frozen sensor → warning
```

## Safety

```text
unsafe quality → reject
unknown prediction → reject
unsafe control → reject
missing model → reject
```

## Orchestrator

```text
bad data → ABSTAIN
quality service unavailable → ABSTAIN
optimization unavailable → ABSTAIN
no safe scenarios → ABSTAIN
```

## Microservices

Проверить реальные HTTP contracts.

## Redis

Проверить publish/consume/ack.

## Docker smoke

Проверить `/health` и `/ready`.

---

# 34. НЕ ЗАПУСКАТЬ TRAINING TESTS

Тесты не должны вызывать дорогое обучение.

Использовать:

- mocks
- existing artifacts
- tiny fixtures
- stub models

Но не `.fit()` больших моделей.

---

# 35. CONFIGURATION

Убрать magic constants в YAML.

Создать/обновить:

```text
configs/
    services.yaml
    controls.yaml
    constraints.yaml
    quality_source_policy.yaml
    tags.yaml
    domain_knowledge.yaml
    runtime.yaml
    monitoring.yaml
    assumptions.yaml
```

---

# 36. ASSUMPTIONS

Все неподтверждённые вещи вынести в:

`configs/assumptions.yaml`

Особенно:

- control ranges
- rate limits
- reliability limits
- source freshness thresholds
- proxy definitions
- surrogate assumptions

---

# 37. DOMAIN EXPERT

Создать:

`reports/domain_review_required.md`

Вынести вопросы для химика:

```text
какие параметры реально управляемые
какие диапазоны допустимы
какие rate-of-change ограничения разумны
какие параметры влияют на серу
какие теги нельзя считать controls
какие proxy производительности/энергии физически осмысленны
какие признаки опасного режима использовать
```

Не блокировать разработку из-за этих вопросов.

Неподтверждённые части переводить в conservative mode / ABSTAIN.

---

# 38. README

Обновить README честно.

Разделить:

```text
Implemented
Working
Experimental
Disabled
Planned
Limitations
```

Отдельно указать:

```text
Model training/retraining intentionally disabled in current development phase.
Existing saved models are used for runtime integration only.
```

---

# 39. ПОРЯДОК РАБОТЫ

## PHASE A — Runtime Audit

```text
technical audit
↓
existing model loading audit
↓
feature schema audit
↓
magic fallback removal
↓
runtime correctness
```

## PHASE B — Agent Logic

```text
StateBuilder
↓
SourceFreshness
↓
QualitySourceResolver
↓
Data Quality
↓
Reliability
↓
Controls
↓
Optimizer
↓
Safety
↓
Orchestrator
```

Без обучения моделей.

## PHASE C — Microservices

```text
separate FastAPI services
↓
shared schemas
↓
HTTP clients
↓
health/readiness
↓
Docker Compose
```

## PHASE D — Event-Driven Runtime

```text
Redis Streams
↓
consumers
↓
replay
↓
runtime events
```

Без training consumers.

## PHASE E — Persistence + Observability

```text
Postgres
↓
Prometheus
↓
Grafana
↓
structured logging
```

## PHASE F — Dashboard + Demo

```text
runtime dashboard
↓
decision trace
↓
historical replay
↓
final smoke test
↓
README
```

---

# 40. ПОСЛЕ КАЖДОГО PHASE

Выводи:

## Найдено

Что было не так.

## Исправлено

Конкретные файлы.

## Команды

Что запускалось.

## Tests

```text
passed
failed
skipped
```

## Runtime status

Какие сервисы работают.

## Known limitations

Что пока нельзя сделать без переобучения моделей.

## Следующий шаг

Конкретно.

---

# 41. DEFINITION OF DONE

Текущий этап считается готовым, когда:

```bash
docker compose up --build
```

поднимает runtime без автоматического обучения моделей.

Работают:

```text
gateway
feature-service
quality-agent
reliability-agent
optimization-agent
safety-agent
orchestrator
dashboard
redis
postgres
prometheus
grafana
```

И можно показать:

```text
historical replay
       ↓
Redis
       ↓
StateBuilder
       ↓
Agents
       ↓
Orchestrator
       ↓
Recommendation / ABSTAIN
       ↓
Postgres
       ↓
Dashboard
       ↓
Prometheus/Grafana
```

При этом:

- ни одна модель не переобучается
- никакой `.fit()` не запускается
- существующие модели не изменяются
- inference либо работает корректно, либо система честно делает ABSTAIN
- magic fallbacks отсутствуют
- Safety Agent fail-closed
- decision trace сохраняется
- сервисы реально разделены
- monitoring реально работает

---

# 42. НАЧНИ СЕЙЧАС

Сейчас выполни:

**PHASE A — Runtime Audit**

Не запускать обучение.

Не запускать дообучение.

Не менять model weights.

Не выполнять hyperparameter search.

Сначала:

1. проинспектируй текущий runtime
2. найди все места, где ML model вызывается некорректно
3. найди magic fallbacks
4. проверь feature schema
5. проверь StateBuilder
6. проверь Docker Compose
7. проверь, какие заявленные сервисы реально существуют
8. создай `reports/technical_audit_runtime.md`
9. исправь безопасные runtime-проблемы, не требующие обучения
10. запусти tests
11. остановись и выдай отчёт

Не переходи к обучению моделей ни при каких обстоятельствах на этом этапе.
