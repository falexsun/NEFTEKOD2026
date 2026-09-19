# MASTER PROMPT: NEFTEKOD2026 — mvp3 runtime integration fixes

Ты работаешь как:

- Senior Python Engineer
- Senior ML Engineer
- MLOps Engineer
- Backend Architect
- Code Reviewer

Репозиторий:

https://github.com/falexsun/NEFTEKOD2026

Рабочая ветка:

`dev`

Текущий базовый коммит:

`mvp2`

Проект — мультиагентная система поддержки принятия решений для производства дизельного топлива:

**АВТ → гидроочистка → блендинг**

Текущий `mvp2` хорошо исправил внутренние классы, но главная проблема сейчас в том, что правильные компоненты ещё не собраны в единый реальный runtime flow.

---

# 0. КРИТИЧЕСКОЕ ОГРАНИЧЕНИЕ

На этом этапе **НЕ обучать и НЕ дообучать модели**.

Запрещено:

```text
.fit()
partial_fit()
CatBoost training
LightGBM training
XGBoost training
Optuna
hyperparameter search
fine-tuning
continual learning
candidate/champion retraining
```

Разрешено:

```text
load existing model
inference
runtime integration
API fixes
StateBuilder fixes
feature buffer
Safety fixes
tests
Docker fixes
```

---

# 1. ГЛАВНАЯ ЦЕЛЬ MVP3

После этого этапа реальный runtime должен работать так:

```text
DecisionRequest
    ↓
normalize raw tags
    ↓
StateBuilder
    ↓
QualitySourceResolver
    ↓
RuntimeFeatureBuffer
    ↓
full feature vector
    ↓
ProcessState
    ↓
Data Quality Agent
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

Главное:

**не создавать новые микросервисы, пока этот flow не работает корректно внутри текущего runtime.**

---

# 2. FIX №1 — NORMALIZE TAGS В `/decision`

Сейчас canonical naming реализован, но API его не использует.

Исправить `src/api/app.py`.

Было логически:

```python
state = ProcessState(
    avt_telemetry=request.avt_telemetry,
    unit_242000_telemetry=request.unit_242000_telemetry,
)
```

Нужно:

```python
from src.shared.tags.normalization import normalize_telemetry_dict

avt_telemetry = normalize_telemetry_dict(
    request.avt_telemetry,
    "avt",
)

u24_telemetry = normalize_telemetry_dict(
    request.unit_242000_telemetry,
    "u24",
)
```

Дальше использовать только:

```text
avt_T1
avt_T6
u24_T5
u24_T6
```

---

# 3. НЕ ДОПУСКАТЬ COLLISION AVT/U24

Нельзя больше делать:

```python
{**raw_avt, **raw_u24}
```

если ключи могут быть:

```text
T6
F9
```

Нужно объединять только canonical dictionaries:

```python
feature_source = {
    **normalized_avt,
    **normalized_u24,
}
```

Тогда:

```text
avt_T6 != u24_T6
```

---

# 4. FIX №2 — `/decision` ОБЯЗАН ИСПОЛЬЗОВАТЬ `StateBuilder`

Сейчас `StateBuilder` реализован, но endpoint фактически его обходит.

Исправить.

Нельзя вручную собирать `ProcessState`, если те же поля уже строит `StateBuilder`.

Желаемый flow:

```python
state = state_builder.build_state(...)
```

---

# 5. РАСШИРИТЬ `DecisionRequest`

Поддержать:

```python
class DecisionRequest(BaseModel):
    timestamp: datetime

    avt_telemetry: dict[str, float]
    avt_timestamp: datetime | None

    unit_242000_telemetry: dict[str, float]
    u24_timestamp: datetime | None

    pak_sulfur_value: float | None
    pak_sulfur_timestamp: datetime | None

    pak_density_value: float | None
    pak_density_timestamp: datetime | None

    lims_values: dict[str, float] | None
    lims_timestamp: datetime | None
```

Можно сохранить обратную совместимость с текущими `sulfur_value/sulfur_ts`, если это нужно.

---

# 6. FIX №3 — НЕ ИГНОРИРОВАТЬ `sulfur_value`

Сейчас request содержит sulfur, но runtime не помещает его в `state.quality`.

Исправить.

При наличии:

```text
pak_sulfur_value
pak_sulfur_timestamp
```

StateBuilder должен создать:

```python
QualitySignal(
    value=...,
    source="PAK",
    measurement_timestamp=...,
    age_minutes=...,
)
```

Без этого:

```text
allow_optimization=False
```

будет почти всегда.

---

# 7. QUALITY SOURCE RESOLVER

Сейчас `configs/quality_source_policy.yaml` есть, но resolver не интегрирован.

Создать:

```text
src/feature_service/quality_source_resolver.py
```

Класс:

```python
QualitySourceResolver
```

Он должен принимать кандидаты:

```text
LIMS
PAK
VAK
```

и выбирать источник по:

```text
priority
freshness
availability
validity
```

---

# 8. ИСПРАВИТЬ НЕСООТВЕТСТВИЕ POLICY

Сейчас комментарий говорит:

```text
LIMS > PAK > VAK
```

но список в YAML начинается с PAK.

Сделать однозначно.

Предпочтительно:

```yaml
priority:
  - LIMS
  - PAK
  - VAK
```

или явное поле:

```yaml
priority: 1
```

у каждого источника.

Не полагаться на случайный порядок YAML.

---

# 9. FRESHNESS ДОЛЖЕН БЫТЬ РЕАЛЬНЫМ

После `StateBuilder` проверить:

```text
source_freshness.avt_minutes
source_freshness.unit_242000_minutes
source_freshness.pak_sulfur_minutes
source_freshness.pak_density_minutes
source_freshness.lims_minutes
```

Data Quality Agent должен получать именно эти значения.

---

# 10. FIX №4 — НУЖЕН `RuntimeFeatureBuffer`

Главный blocker сейчас:

```text
Quality Model expects 721 features
runtime gives only raw telemetry
```

Нужно создать:

```text
src/feature_service/runtime_buffer.py
```

Класс:

```python
RuntimeFeatureBuffer
```

---

# 11. ЧТО ДОЛЖЕН ХРАНИТЬ BUFFER

Минимально:

```text
timestamp
AVT telemetry
U24 telemetry
PAK values
LIMS values
```

История должна быть достаточной для построения:

```text
lags
rolling mean
rolling std
rolling min
rolling max
delta
rate of change
slope
```

---

# 12. НЕ СТРОИТЬ LAG FEATURES ИЗ ОДНОЙ ТОЧКИ

Если модель ожидает, например:

```text
lag_10m
lag_30m
lag_1h
rolling_2h
rolling_6h
```

при старте runtime эти features недоступны.

Правильное поведение:

```text
history_not_ready
→ prediction unavailable
→ ABSTAIN
```

Нельзя:

```text
missing lag → 0
```

---

# 13. REPLAY ДОЛЖЕН ПРОГРЕВАТЬ BUFFER

При historical replay:

```text
row 1
row 2
...
row N
```

должны последовательно попадать в `RuntimeFeatureBuffer`.

После достаточного количества истории:

```text
feature_ready=True
```

и только тогда разрешать Quality inference.

---

# 14. НЕ ДУБЛИРОВАТЬ FEATURE ENGINEERING

Не создавать новый набор формул для runtime отдельно от training pipeline.

Нужно переиспользовать существующую feature engineering логику.

Если текущая `build_features()` работает только batch-режимом:

выделить общие функции:

```text
build_lags()
build_rollings()
build_deltas()
build_slopes()
```

и использовать их:

```text
training
+
runtime
```

---

# 15. FEATURE VECTOR ДОЛЖЕН СОВПАДАТЬ С MODEL SCHEMA

Перед inference:

```python
expected = quality_agent.model_metadata.feature_names
```

RuntimeFeatureBuffer должен сформировать:

```python
state.feature_vector
```

с ровно этими ключами.

Проверять:

```text
expected feature count
actual feature count
missing
extra
```

---

# 16. FIX №5 — SURROGATE STRICT SCHEMA

Сейчас Surrogate использует:

```python
modified_features.get(k, 0.0)
```

Это нужно убрать.

Перед inference:

```python
missing = [
    f for f in self.feature_names
    if f not in modified_features
]
```

Если `missing`:

```python
return SimulationResult(
    status="unavailable",
    availability_reason=...
)
```

Не подставлять `0.0`.

---

# 17. SURROGATE — НЕ ДОПУСКАТЬ НЕМАППИНГОВАННЫЕ CONTROLS

Сейчас control без mapping может silently пропускаться.

Лучше:

```text
control requested
but mapping absent
→ scenario unavailable
```

или такой control исключать из optimization заранее.

Не считать scenario изменённым, если action фактически не применился.

---

# 18. FIX №6 — QUALITY UNCERTAINTY

`std=1.5` пока допустим только как временный assumption.

Перенести из Python в config:

```yaml
quality_uncertainty:
  method: approximate_fixed_std
  sulfur_std: 1.5
```

Не hardcode.

---

# 19. MODEL CONFIDENCE ОСТАВЛЯТЬ `None`

Правильно:

```text
violation_probability != confidence
```

Не возвращать fake confidence.

---

# 20. FIX №7 — `Recommendation.confidence`

Сейчас `QualityPrediction.confidence` допускает `None`, но `Recommendation.confidence` всё ещё float.

Исправить schema:

```python
confidence: float | None = None
```

Иначе при реальной recommendation возможен Pydantic ValidationError.

---

# 21. ДОБАВИТЬ TEST НА `confidence=None`

Тест:

```python
Recommendation(
    ...,
    confidence=None,
)
```

должен успешно валидироваться.

---

# 22. FIX №8 — SAFETY `max_step`

`ControlRegistry` уже умеет:

```python
validate_control_value(
    name,
    value,
    current=current,
)
```

Но Safety сейчас не передаёт `current`.

Исправить.

Safety должен знать текущий ProcessState.

---

# 23. ИЗМЕНИТЬ SIGNATURE SAFETY CHECK

Например:

```python
check_scenario(
    scenario,
    quality_pred,
    data_quality_score,
    state: ProcessState,
)
```

Для каждого action:

```python
current = (
    state.avt_telemetry.get(param)
    or state.unit_242000_telemetry.get(param)
)
```

Но аккуратно: `0` — валидное значение, поэтому лучше явно:

```python
if param in state.avt_telemetry:
    current = state.avt_telemetry[param]
elif param in state.unit_242000_telemetry:
    current = state.unit_242000_telemetry[param]
else:
    current = None
```

---

# 24. SAFETY ДОЛЖЕН ПРОВЕРЯТЬ `max_step`

Передать:

```python
validate_control_value(
    param,
    value,
    current=current,
)
```

---

# 25. `max_rate_of_change`

Если `ControlSpec.max_rate_of_change` есть и RuntimeFeatureBuffer имеет предыдущие значения:

проверять.

Если нет истории:

```text
rate check unavailable
```

и применять conservative policy.

---

# 26. FIX №9 — `/safety/check` ДОЛЖЕН ПРОВЕРЯТЬ ACTION

Сейчас request содержит:

```python
action
```

но endpoint проверяет только quality prediction.

Переделать.

Создать `ScenarioEvaluation` из request и вызвать:

```python
agent.check_scenario(...)
```

---

# 27. SAFETY ENDPOINT INPUT

Лучше schema:

```python
class SafetyCheckRequest(BaseModel):
    predicted_sulfur: float
    sulfur_std: float
    violation_probability: float
    data_quality_score: float

    reliability_risk: float
    ood_score: float

    action: dict[str, float]
    current_state: dict[str, float]
```

Никаких magic defaults.

---

# 28. FIX №10 — OPTIMIZER НЕ ДОЛЖЕН ИМЕТЬ MAGIC DEFAULTS

Сейчас:

```python
result.predictions.get("sulfur", 0.0)
result.predictions.get("sulfur_std", 5.0)
```

убрать.

Если:

```text
sulfur missing
or
sulfur_std missing
```

то:

```text
simulation_status="error"
```

и scenario не участвует в ranking.

---

# 29. `NO CHANGE` СЦЕНАРИЙ

Проверить, что после normalization:

```text
NO CHANGE
```

реально содержит текущие control values.

Не `{}`.

---

# 30. ЕСЛИ НЕТ НИ ОДНОГО CONTROL CURRENT VALUE

Не генерировать пустой candidate как будто это валидный scenario.

Вернуть:

```text
candidate_generation_unavailable
```

или пустой список + explicit status.

---

# 31. DATA QUALITY — УБРАТЬ COLLISION В HISTORY

DataQuality Agent всё ещё использует:

```python
{**state.avt_telemetry, **state.unit_242000_telemetry}
```

Это безопасно только если state уже canonical.

После изменения API убедиться, что StateBuilder всегда сохраняет canonical names.

Добавить assertion/test.

---

# 32. DATA QUALITY THRESHOLDS

Пока можно оставить proxy thresholds, но вынести:

```text
max_stale_minutes
frozen_window
jump_threshold
```

в config.

Не hardcode в runtime классе.

---

# 33. RELIABILITY

Проверить, что agent больше не добавляет prefix второй раз:

```text
avt_avt_T1
```

если state уже canonical.

Логика должна быть:

```python
if key.startswith("avt_"):
    use key
else:
    normalize
```

То же для u24.

---

# 34. OPERATING ENVELOPE

Если operating envelope отсутствует:

оставить proxy baseline risk.

Но явно:

```text
operating_envelope_available=False
```

желательно добавить в `ReliabilityAssessment`.

---

# 35. API `/ready`

Сделать readiness более информативным:

```json
{
  "prediction_ready": false,
  "feature_history_ready": false,
  "quality_model_ready": true,
  "optimization_ready": false,
  "surrogate_ready": false
}
```

То есть model ready ≠ runtime prediction ready.

---

# 36. ДОБАВИТЬ `feature_history_ready`

Если buffer ещё не прогрет:

```text
prediction_ready=false
```

даже если модель успешно загружена.

---

# 37. `/model/info`

Дополнить:

```text
feature_count
runtime_feature_count
runtime_schema_match
history_ready
```

---

# 38. FIX №11 — HTTP INTEGRATION TEST `/decision`

Нужен настоящий test через FastAPI TestClient.

Не только прямой вызов Orchestrator.

Тестировать endpoint.

---

# 39. TEST: RAW TAG NORMALIZATION

Input:

```json
{
  "avt_telemetry": {"T6": 234},
  "unit_242000_telemetry": {"T6": 8.5}
}
```

Внутри runtime должно стать:

```text
avt_T6 = 234
u24_T6 = 8.5
```

оба значения должны сохраниться.

---

# 40. TEST: SULFUR REQUEST INTEGRATION

Передать:

```text
sulfur_value=7.5
sulfur_ts=current-10min
```

Проверить:

```text
state.quality["sulfur"]
```

существует.

---

# 41. TEST: FRESHNESS

Проверить:

```text
PAK 10 min old
→ pak_sulfur_minutes = 10
```

---

# 42. TEST: FEATURE BUFFER NOT READY

Первые точки replay:

```text
history insufficient
→ /decision returns ABSTAIN
```

с причиной:

```text
feature history not ready
```

---

# 43. TEST: FEATURE BUFFER READY

После достаточного количества history:

```text
feature_vector count == model expected count
```

Если текущие реальные formulas позволяют.

Не обучать модель.

---

# 44. TEST: SURROGATE MISSING FEATURE

Если feature отсутствует:

```text
SimulationResult.status == unavailable
```

а не нулевой fallback.

---

# 45. TEST: SAFETY MAX STEP

Пример:

```text
current avt_T1 = 130
max_step = 5
candidate = 150
```

Safety обязан reject.

---

# 46. TEST: SAFETY ACTION ENDPOINT

Через HTTP:

```json
{
  "predicted_sulfur": 5,
  "sulfur_std": 1,
  "violation_probability": 0.01,
  "action": {
    "avt_T1": 999
  }
}
```

должен быть reject.

---

# 47. TEST: `Recommendation confidence=None`

Обязательный regression test.

---

# 48. TEST: OPTIMIZER MISSING PREDICTION

Если surrogate возвращает:

```python
SimulationResult(
    status="ok",
    predictions={}
)
```

Optimizer должен считать scenario ошибочным.

---

# 49. DOCKER

Не менять текущее правило:

```text
trainer disabled by default
```

Default:

```bash
docker compose up --build
```

не должен запускать training.

---

# 50. НЕ ПЕРЕХОДИТЬ К МИКРОСЕРВИСАМ ПОКА

Пока не делать:

```text
quality-agent container
reliability-agent container
optimizer container
...
```

Сначала добиться настоящего working runtime.

---

# 51. НЕ ДОБАВЛЯТЬ ПОКА GRAFANA

Grafana/Prometheus отложить до завершения этого этапа.

Priority:

```text
runtime correctness
> integration
> safety
> behavioral tests
> microservices
> monitoring
```

---

# 52. REPORT

Создать:

```text
reports/runtime_fix_v3.md
```

Обязательно написать:

## Implemented

Что реально подключено.

## Runtime flow

Фактическая цепочка.

## Feature buffer

Как работает.

## Model compatibility

Сколько features ожидает модель и сколько реально формирует runtime.

## Safety

Какие checks реально работают.

## Tests

```text
passed
failed
skipped
```

## Known limitations

Без преувеличений.

---

# 53. НЕ ПИСАТЬ В REPORT ТО, ЧТО НЕ ПОДКЛЮЧЕНО

Если:

```text
QualitySourceResolver
```

только создан, но endpoint его не использует:

писать:

```text
implemented but not integrated
```

а не:

```text
working
```

---

# 54. DEFINITION OF DONE

MVP3 считается готовым, если:

1. `/decision` нормализует теги;
2. AVT/U24 collisions исключены;
3. `/decision` использует StateBuilder;
4. sulfur input реально попадает в state;
5. SourceFreshness реально работает;
6. QualitySourceResolver интегрирован;
7. RuntimeFeatureBuffer существует;
8. при недостаточной истории система ABSTAIN;
9. при достаточной истории runtime пытается собрать полный model schema;
10. Surrogate strict по missing features;
11. Safety реально проверяет max_step;
12. `/safety/check` реально проверяет action;
13. Recommendation поддерживает confidence=None;
14. Optimizer не использует magic prediction defaults;
15. HTTP integration tests проходят;
16. никакая модель не обучалась;
17. default Docker runtime не запускает trainer.

---

# 55. НАЧНИ СЕЙЧАС

Работай в таком порядке:

```text
1. API tag normalization
2. StateBuilder integration
3. sulfur/freshness integration
4. QualitySourceResolver
5. RuntimeFeatureBuffer
6. model schema matching
7. Surrogate strict schema
8. Safety current/max_step
9. Safety endpoint
10. Recommendation confidence fix
11. Optimizer magic defaults removal
12. HTTP behavioral tests
13. runtime_fix_v3.md
```

Не переходи к микросервисам.

Не запускай обучение.

Не добавляй Grafana.

Сначала добейся корректного runtime integration.
