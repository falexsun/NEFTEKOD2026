# MASTER PROMPT: NEFTEKOD2026 Runtime Fix v2 — без обучения моделей

Ты работаешь как:

- Senior Python Engineer
- Senior ML Engineer
- MLOps Engineer
- Backend/Microservices Architect
- Code Reviewer

Репозиторий:

https://github.com/falexsun/NEFTEKOD2026

Рабочая ветка:

`dev`

Текущий последний коммит:

`mvp1`

Проект — мультиагентная система поддержки принятия решений для производства дизельного топлива:

**АВТ → гидроочистка → блендинг**

Твоя задача — **не переписывать проект с нуля**, а исправить конкретные runtime-проблемы текущего `mvp1`, выявленные после технического аудита.

---

# 0. КРИТИЧЕСКОЕ ОГРАНИЧЕНИЕ

На этом этапе **ЗАПРЕЩЕНО обучать, переобучать или дообучать модели**.

Не запускать:

- `.fit()`
- `partial_fit()`
- CatBoost training
- LightGBM training
- XGBoost training
- Optuna
- hyperparameter search
- fine-tuning
- neural network training
- continual learning
- candidate/champion retraining
- model promotion

Разрешено:

- загружать уже существующие модели;
- выполнять inference;
- чинить schema/inference wiring;
- улучшать runtime;
- улучшать API;
- улучшать safety;
- улучшать тесты;
- улучшать Docker;
- улучшать агенты;
- добавлять monitoring infrastructure.

---

# 1. ГЛАВНАЯ ЦЕЛЬ

Исправить текущий runtime foundation до состояния, когда:

```text
raw/replay data
    ↓
StateBuilder
    ↓
FeatureBuilder
    ↓
ProcessState + FeatureVector
    ↓
Quality Agent
    ↓
Reliability Agent
    ↓
Optimization Agent
    ↓
Safety Agent
    ↓
Orchestrator
    ↓
Recommendation / ABSTAIN
```

работает честно и безопасно.

Если какая-либо критическая часть недоступна:

```text
ABSTAIN
```

Никаких fake predictions.

---

# 2. СНАЧАЛА ПРОВЕРЬ ТЕКУЩИЙ `mvp1`

Перед изменениями:

1. прочитай `reports/technical_audit_runtime.md`;
2. изучи текущие изменения в:
   - `src/agents/quality/agent.py`
   - `src/agents/orchestrator/agent.py`
   - `src/agents/optimization/agent.py`
   - `src/agents/surrogate/model.py`
   - `src/agents/safety/agent.py`
   - `src/agents/data_quality/agent.py`
   - `src/agents/reliability/agent.py`
   - `src/api/app.py`
   - `src/feature_service/state_builder.py`
3. изучи:
   - `src/training/models.py`
   - `src/feature_service/features.py`
   - `configs/controls.yaml`
   - `configs/tags.yaml`
   - `docker-compose.yml`
   - tests;
4. не доверяй комментариям в коде без проверки.

---

# 3. КРИТИЧЕСКИЙ FIX №1 — FEATURE NAMES И MODEL WRAPPER

Сейчас сохранённые модели — wrapper-классы:

```python
CatBoostModel
LightGBMModel
XGBoostModel
```

и реальная estimator-модель находится внутри:

```python
wrapper.model
```

Текущий `QualityAgent._extract_feature_names()` может проверять feature names у wrapper, а не у внутренней модели.

Исправить.

Использовать:

```python
estimator = getattr(model, "model", model)
```

и затем извлекать feature names из `estimator`.

Поддержать:

```text
CatBoostRegressor
LightGBM
XGBoost
sklearn-compatible estimators
```

---

# 4. ПОЛНОСТЬЮ УБРАТЬ `sorted(feature_vector.keys())`

Запрещён runtime fallback:

```python
feature_names = sorted(feature_vector.keys())
```

Если `ModelArtifactMetadata` отсутствует:

```text
Quality Agent → model_available=False
→ ABSTAIN
```

Не пытаться угадывать порядок features.

То же правило для Surrogate Model.

---

# 5. FEATURE SCHEMA VALIDATION

Текущая логика schema validation должна быть строгой.

Если отсутствует хотя бы один обязательный feature, необходимо определить policy.

Для текущего этапа использовать conservative policy:

```text
missing critical/expected feature
→ inference unavailable
→ ABSTAIN
```

Не разрешать:

```python
feature_vector.get(k, 0.0)
```

для отсутствующих ожидаемых признаков.

Допускается заполнение `0/NaN` только если это явно было частью training preprocessing и это подтверждено.

Иначе:

```text
schema mismatch
```

---

# 6. ДОБАВИТЬ MODEL ARTIFACT INFO ENDPOINT

Quality Agent должен уметь отдавать:

```text
model name
model version
target
horizon
feature count
feature schema available
ready status
```

Например:

```http
GET /model/info
```

Ответ:

```json
{
  "model_available": true,
  "model_ready": true,
  "model_name": "catboost_champion.pkl",
  "target": "sulfur",
  "horizon_minutes": 60,
  "feature_count": 721
}
```

---

# 7. КРИТИЧЕСКИЙ FIX №2 — ЕДИНАЯ СИСТЕМА ИМЕН ТЕГОВ

Сейчас могут использоваться разные формы:

```text
T5
avt_T5
u24_T5
u242000_T5
```

Это недопустимо.

Нужно ввести canonical tag identifiers.

Предпочтительно:

```text
avt.T1
avt.F3
u24.T5
u24.F15
```

или другой единый формат.

Главное — выбрать ОДИН формат и использовать его во всём runtime.

---

# 8. TAG NORMALIZATION LAYER

Создать отдельный модуль:

```text
src/shared/tags/
    registry.py
    normalization.py
```

Например:

```python
normalize_tag(
    source="avt",
    raw_name="T1"
) -> "avt.T1"
```

и:

```python
normalize_tag(
    source="u24",
    raw_name="T5"
) -> "u24.T5"
```

Все runtime agents должны работать с canonical names.

---

# 9. НЕ ДОПУСКАТЬ COLLISION AVT И U24

Сейчас конструкция:

```python
{**state.avt_telemetry, **state.unit_242000_telemetry}
```

может уничтожить значения, если в обоих источниках есть:

```text
T6
F9
...
```

Исправить.

Должно быть:

```text
avt.T6
u24.T6
```

и никакого overwrite.

Это особенно важно для:

- Data Quality Agent;
- Reliability Agent;
- frozen sensor history;
- jump detection;
- optimizer.

---

# 10. CONFIGS/CONTROLS.YAML ПРИВЕСТИ К CANONICAL NAMES

После выбора canonical naming привести `controls.yaml` к нему.

Например:

```yaml
variables:
  avt.T1:
    ...
  u24.T5:
    ...
```

Не должно быть смешения:

```text
u24_T5
u242000_T5
T5
```

---

# 11. CONTROL REGISTRY

Реализовать настоящий:

```text
ControlRegistry
```

Он должен читать:

`configs/controls.yaml`

И отдавать:

```python
ControlSpec(
    name,
    semantic_name,
    unit,
    stage,
    role,
    model_range,
    max_step,
    max_rate_of_change,
    source,
    confidence,
)
```

Optimizer работает ТОЛЬКО через `ControlRegistry`.

---

# 12. КРИТИЧЕСКИЙ FIX №3 — `/decision` ДОЛЖЕН ИСПОЛЬЗОВАТЬ STATE BUILDER

Сейчас `/decision` не должен создавать `ProcessState` напрямую из raw dict и сразу передавать в Orchestrator.

Нужно сделать:

```text
DecisionRequest
    ↓
normalize tags
    ↓
StateBuilder
    ↓
FeatureBuilder
    ↓
ProcessState
    ↓
Orchestrator
```

---

# 13. DECISION REQUEST SCHEMA

Расширить request так, чтобы можно было передать:

```text
timestamp
AVT timestamp
U24 timestamp
PAK sulfur
PAK sulfur timestamp
PAK density
PAK density timestamp
LIMS values
LIMS timestamp
```

Если часть отсутствует — корректно сохранить `None`.

---

# 14. PROCESSSTATE FEATURE VECTOR

`ProcessState` уже содержит:

```python
feature_vector
```

Использовать это поле.

Не передавать feature vector параллельно отдельным аргументом, если можно избежать двойного источника истины.

Предпочтительно:

```python
state.feature_vector
```

как canonical runtime feature vector.

---

# 15. FEATURE BUILDER ДЛЯ RUNTIME

Нужно определить честный способ формирования 721 features на runtime.

Если для их формирования требуется история:

- создать history buffer;
- либо feature cache;
- либо state store.

Нельзя создать lag/rolling features из одной точки.

Если история недоступна:

```text
feature pipeline not ready
→ ABSTAIN
```

Не подставлять нули молча.

---

# 16. RUNTIME FEATURE BUFFER

Если нужно, реализовать:

```text
RuntimeFeatureBuffer
```

Хранит последние N точек:

```text
AVT
U24
PAK
```

Для построения:

```text
lags
rolling
delta
slope
```

Должен работать и для replay mode.

---

# 17. SOURCE FRESHNESS ДОЛЖЕН ИСПОЛЬЗОВАТЬСЯ В API

StateBuilder уже умеет рассчитывать freshness.

Подключить его к реальному runtime.

Проверить:

```text
AVT age
U24 age
PAK sulfur age
PAK density age
LIMS age
```

Data Quality Agent должен видеть эти значения.

---

# 18. QUALITY SOURCE RESOLVER

Если ещё не реализован — добавить.

Создать:

```text
src/feature_service/quality_source_resolver.py
```

Policy:

```text
LIMS > PAK > VAK
```

но учитывать freshness.

Создать config:

```text
configs/quality_source_policy.yaml
```

Не hardcode thresholds внутри агента.

---

# 19. `/READY` ИСПРАВИТЬ

Quality Agent уже различает:

```python
is_available
is_ready
```

`/ready` обязан использовать:

```python
is_ready
```

а не просто `is_available`.

---

# 20. `/READY` ДОЛЖЕН УЧИТЫВАТЬ SURROGATE

Если `/decision` требует surrogate для оптимизации:

```text
surrogate unavailable
→ optimization unavailable
```

Readiness нужно разделить:

```json
{
  "prediction_ready": true,
  "optimization_ready": false,
  "services": {
    "quality": true,
    "surrogate": false
  }
}
```

Не обязательно считать весь gateway полностью `not ready`, если prediction mode работает.

---

# 21. SURROGATE — УБРАТЬ НЕПРАВИЛЬНЫЙ SUBSTRING MATCHING

Запрещено:

```python
if param in feat_name:
    modified_features[feat_name] = value
```

Потому что изменение:

```text
avt.T1
```

не должно менять:

```text
avt.T1_lag1
avt.T1_rmean6
avt.T11
```

Изменять только current control feature по exact mapping.

---

# 22. SURROGATE FEATURE MAPPING

Создать mapping:

```text
control canonical name
→ exact model feature name
```

Например:

```yaml
avt.T1: avt_T1
u24.T5: u24_T5
```

или генерировать deterministic mapping через registry.

Никакого substring matching.

---

# 23. SURROGATE HISTORY НЕ ПЕРЕПИСЫВАТЬ

При candidate action:

```text
current control changes
```

но:

```text
lag features
rolling history
previous values
```

остаются историческими.

Если корректная what-if simulation невозможна без рекурсивной dynamics model:

честно ограничить модель.

Не имитировать физику.

---

# 24. SURROGATE UNCERTAINTY

Сейчас `sulfur_std = 1.5` — assumption.

На текущем этапе без переобучения:

- вынести значение в config;
- явно назвать `approximate_uncertainty`;
- добавить assumption в `configs/assumptions.yaml`;
- не называть confidence статистически калиброванной.

---

# 25. QUALITY CONFIDENCE

Не использовать:

```python
confidence = 1 - violation_probability
```

как model confidence.

Это разные величины.

Разделить:

```text
violation_probability
uncertainty
model_confidence
```

Если настоящего model confidence нет:

```text
model_confidence = None
```

Если schema не позволяет `None` — обновить schema.

---

# 26. SAFETY ENDPOINT — УБРАТЬ MAGIC DEFAULTS

Сейчас endpoint типа:

```text
/safety/check
```

не должен иметь:

```python
predicted_sulfur=7.0
sulfur_std=1.5
violation_probability=0.1
confidence=0.5
```

по умолчанию.

Все критические поля должны быть обязательными или приходить в typed Pydantic request.

---

# 27. SAFETY REQUEST SCHEMA

Создать:

```python
SafetyCheckRequest(
    scenario,
    quality_prediction,
    data_quality_score,
    control_context,
)
```

Не использовать разрозненные query params.

---

# 28. SAFETY — CONTROL RANGE CHECK

Safety Agent обязан проверять:

```text
control within model trust region
```

через ControlRegistry.

---

# 29. SAFETY — MAX STEP

Проверять:

```text
abs(recommended - current) <= max_step
```

если `max_step` известен.

Если неизвестен:

- не придумывать;
- использовать conservative behavior;
- либо пометить scenario как `requires expert validation`.

---

# 30. SAFETY — RATE OF CHANGE

Если есть история:

```text
max_rate_of_change
```

проверять реально.

Не использовать fake absolute threshold.

---

# 31. SAFETY — UNKNOWN UNCERTAINTY

Если uncertainty критично нужна для hard quality gate, но отсутствует:

```text
REJECT / ABSTAIN
```

не разрешать сценарий.

---

# 32. DATA QUALITY — HISTORY STATE

Data Quality Agent сейчас stateful.

При будущем микросервисном разнесении это важно.

На данном этапе:

- сохранить singleton lifecycle;
- не создавать DataQualityAgent на каждый request;
- history должна сохраняться между точками replay.

---

# 33. RELIABILITY — HISTORY COLLISION FIX

Исправить историю так, чтобы:

```text
avt.T6
u24.T6
```

были разными сигналами.

---

# 34. RELIABILITY BASELINE RISK

Сейчас:

```python
overall_risk = 0.1
```

если факторов нет.

Это допустимо только как proxy assumption.

Вынести в config и задокументировать.

Не выдавать как статистически рассчитанный risk.

---

# 35. OPTIMIZER BASELINE SCENARIO

Проверить, что `NO CHANGE` действительно содержит текущие значения controls.

Из-за naming mismatch он не должен быть `{}`.

Добавить test:

```text
NO CHANGE action == current values for all available controls
```

---

# 36. OPTIMIZER — НЕ БРАТЬ MIDPOINT ПРИ ОТСУТСТВУЮЩЕМ CURRENT VALUE

Запрещено:

```python
current = (low + high) / 2
```

если текущего control signal нет.

В таком случае:

```text
skip this control
```

или:

```text
scenario generation unavailable
```

но не придумывать current process value.

---

# 37. PRODUCTION / ENERGY PROXY

Если semantic tag lists не настроены:

```text
proxy unavailable
```

или `None`.

Лучше не использовать `0.0` как будто это реальный эффект.

Обновить schema при необходимости:

```python
production_proxy: float | None
energy_proxy: float | None
```

---

# 38. DOCKER — TRAINER УБРАТЬ ИЗ DEFAULT START

На текущем этапе trainer не должен запускаться автоматически.

В `docker-compose.yml`:

```yaml
trainer:
  profiles:
    - training
```

Если `trainer_service` отсутствует — default runtime всё равно должен работать.

---

# 39. DOCKER DEFAULT RUNTIME

Команда:

```bash
docker compose up --build
```

не должна:

- запускать обучение;
- падать из-за trainer;
- требовать GPU.

---

# 40. DOCKER SMOKE TEST

Проверить:

```text
gateway /health
gateway /ready
dashboard
redis
postgres
mlflow optional
minio optional
```

Если какие-то optional сервисы не нужны runtime — вынести в profiles.

---

# 41. TESTS — ОБЯЗАТЕЛЬНО УСИЛИТЬ

Не ограничиваться:

```python
assert isinstance(result, Recommendation | AbstainRecommendation)
```

---

# 42. TEST: MODEL WRAPPER FEATURE NAMES

Добавить test:

```text
load CatBoostModel wrapper
↓
extract internal estimator feature names
↓
metadata.feature_names not empty
```

Использовать existing artifact или stub wrapper.

Без `.fit()`.

---

# 43. TEST: NO SORTED FALLBACK

Если feature metadata отсутствует:

```text
QualityAgent.predict
→ model_available=False
```

а не prediction.

---

# 44. TEST: SCHEMA MISMATCH

```text
model expects 721 features
request gives incomplete feature vector
→ ABSTAIN
```

---

# 45. TEST: CANONICAL TAG COLLISION

Проверить:

```text
AVT T6
U24 T6
```

после normalization:

```text
avt.T6 != u24.T6
```

---

# 46. TEST: CONTROL REGISTRY

Проверить:

- state-only tag не попадает в optimizer;
- control_candidate попадает;
- unknown tag не попадает.

---

# 47. TEST: NO CHANGE

Проверить:

```text
baseline candidate
```

равен текущим control values.

---

# 48. TEST: SURROGATE EXACT FEATURE MAPPING

При action:

```text
avt.T1 -> 150
```

изменяется только:

```text
avt_T1
```

но НЕ:

```text
avt_T1_lag1
avt_T1_rmean6
avt_T11
```

---

# 49. TEST: SAFETY NO DEFAULTS

Safety endpoint должен возвращать validation error, если не переданы обязательные safety inputs.

---

# 50. TEST: SURROGATE UNAVAILABLE

```text
surrogate unavailable
→ optimization unavailable
→ orchestrator ABSTAIN
```

---

# 51. TEST: STALE DATA

```text
stale PAK/LIMS
→ allow_prediction maybe true
→ allow_optimization false
```

---

# 52. TEST: FEATURE HISTORY NOT READY

При старте replay и недостаточной истории для rolling features:

```text
runtime features not ready
→ ABSTAIN
```

а не fake zero-filled vector.

---

# 53. TEST: DOCKER DEFAULT WITHOUT TRAINER

Убедиться, что:

```bash
docker compose up --build
```

не требует trainer service.

---

# 54. НЕ ТРОГАТЬ ОБУЧЕНИЕ

Не изменять:

```text
model weights
training metrics
baseline comparison
hyperparameters
training pipeline behavior
```

кроме безопасных рефакторингов, необходимых для inference compatibility.

Не запускать `scripts/run_pipeline.py`, если он обучает модели.

---

# 55. REPORT

Создать новый:

```text
reports/runtime_fix_v2.md
```

Структура:

## Fixed

Что исправлено.

## Remaining limitations

Что всё ещё нельзя сделать.

## Runtime path

Фактическая схема.

## Model integration

Работает ли существующий artifact.

## Tests

Сколько:

```text
passed
failed
skipped
```

## Docker

Какие сервисы поднимаются.

## Known ABSTAIN cases

Список причин.

---

# 56. ОБНОВИТЬ TECHNICAL AUDIT

После изменений обновить:

```text
reports/technical_audit_runtime.md
```

Не удалять историю проблем.

Лучше добавить:

```text
Status after mvp2
```

---

# 57. ПОРЯДОК РАБОТЫ

Работать в таком порядке:

## PHASE 1 — Inference correctness

```text
model wrapper
↓
feature metadata
↓
remove sorted fallback
↓
strict schema
↓
ready status
```

## PHASE 2 — Tag consistency

```text
canonical naming
↓
tag normalizer
↓
control registry
↓
fix collisions
```

## PHASE 3 — Runtime state

```text
StateBuilder
↓
feature buffer
↓
feature vector
↓
source freshness
↓
decision endpoint
```

## PHASE 4 — Decision safety

```text
optimizer baseline
↓
surrogate exact mapping
↓
safety controls
↓
no magic defaults
```

## PHASE 5 — Docker

```text
disable default trainer
↓
health/readiness
↓
smoke test
```

## PHASE 6 — Tests + report

```text
behavioral tests
↓
runtime report
↓
README update if needed
```

---

# 58. НЕ ПЕРЕХОДИТЬ ПОКА К ПОЛНОЦЕННЫМ МИКРОСЕРВИСАМ

На этом этапе НЕ нужно сразу создавать 8 новых Docker agent services.

Сначала добиться корректного in-process runtime.

После этого можно разносить компоненты.

Причина:

```text
не размножать runtime bugs по микросервисам
```

---

# 59. НЕ ПЕРЕХОДИТЬ ПОКА К GRAFANA

Prometheus/Grafana пока можно не добавлять, если это мешает runtime fixes.

Priority:

```text
runtime correctness
> safety
> tests
> microservices
> observability
```

---

# 60. DEFINITION OF DONE

Этап считается готовым, когда:

1. существующая модель либо корректно загружается с feature schema, либо Quality Agent честно unavailable;
2. `sorted(feature_vector.keys())` полностью отсутствует из critical inference path;
3. AVT и U24 теги не конфликтуют;
4. controls используют canonical names;
5. `/decision` проходит через StateBuilder;
6. runtime feature vector строится честно;
7. недостаточная история → ABSTAIN;
8. surrogate не переписывает lag/rolling по substring;
9. Safety проверяет control ranges;
10. trainer не стартует по умолчанию;
11. Docker runtime не обучает модели;
12. behavioral tests проходят;
13. создан `reports/runtime_fix_v2.md`.

---

# 61. НАЧНИ СЕЙЧАС

Сейчас выполни только этот runtime-fix этап.

Не обучай модели.

Не создавай новые ML-модели.

Не запускай training pipeline.

Не добавляй Grafana до завершения critical runtime fixes.

Сначала исправь:

1. feature metadata extraction;
2. remove sorted fallback;
3. canonical tags;
4. StateBuilder integration;
5. runtime feature vector;
6. ControlRegistry;
7. Surrogate exact mapping;
8. Safety controls;
9. trainer Docker profile;
10. behavioral tests.

После этого остановись и покажи подробный отчёт.
