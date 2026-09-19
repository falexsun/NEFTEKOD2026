# MASTER PROMPT: NEFTEKOD2026 — MVP4 Fix-All Runtime Foundation

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

Текущая база:

`mvp3`

Проект — мультиагентная система поддержки принятия решений для производства дизельного топлива:

**АВТ → гидроочистка → блендинг**

Твоя задача — **исправить все оставшиеся runtime-проблемы после MVP3**, не переписывая проект с нуля и не переходя пока к полноценным микросервисам.

---

# 0. КРИТИЧЕСКОЕ ОГРАНИЧЕНИЕ

На этом этапе **НЕ обучать, НЕ переобучать и НЕ дообучать модели**.

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
deep learning training
continual learning
candidate/champion retraining
model promotion
```

Разрешено:

```text
load existing models
inference
runtime integration
feature pipeline refactor
StateBuilder fixes
QualitySourceResolver integration
Safety fixes
API fixes
tests
Docker fixes
config integration
```

---

# 1. ГЛАВНАЯ ЦЕЛЬ MVP4

После этого этапа текущий in-process runtime должен быть действительно рабочим:

```text
DecisionRequest
    ↓
timestamp validation
    ↓
tag normalization
    ↓
QualitySourceResolver
    ↓
RuntimeFeatureBuffer
    ↓
shared FeatureTransformer
    ↓
full model feature vector
    ↓
StateBuilder
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
Surrogate
    ↓
Safety Agent
    ↓
Orchestrator
    ↓
Recommendation / AbstainRecommendation
```

Главная цель:

**убрать все расхождения между training и runtime feature engineering и сделать один реальный источник истины для feature pipeline.**

---

# 2. FIX №1 — КРИТИЧЕСКИЙ БАГ `StateBuilder(avt_cols=[], u24_cols=[])`

Сейчас runtime создаёт:

```python
_state_builder = StateBuilder(avt_cols=[], u24_cols=[])
```

а `build_state()` затем проходит по этим пустым спискам и формирует:

```python
avt_telemetry = {}
unit_242000_telemetry = {}
```

Это ломает весь runtime.

Исправить архитектуру.

---

# 3. STATEBUILDER НЕ ДОЛЖЕН ЗАВИСЕТЬ ОТ ПУСТЫХ COLUMN LISTS В RUNTIME

Лучший вариант — изменить API `StateBuilder`:

```python
state = state_builder.build_state(
    timestamp=ts,
    avt_telemetry=avt,
    unit_242000_telemetry=u24,
    quality=...,
    ...
)
```

То есть telemetry передаётся напрямую.

Если нужна обратная совместимость с batch pipeline — можно оставить старый метод как отдельный:

```python
build_state_from_row(...)
```

а runtime использовать:

```python
build_state_from_runtime(...)
```

Не смешивать два разных сценария.

---

# 4. STATEBUILDER ДОЛЖЕН СОХРАНЯТЬ CANONICAL TAGS

После normalization:

```text
avt_T6
u24_T6
```

StateBuilder обязан сохранить именно эти ключи.

Нельзя повторно prefix'ить:

```text
avt_avt_T6
u24_u24_T6
```

---

# 5. ДОБАВИТЬ TEST НА STATEBUILDER RUNTIME

Input:

```python
avt = {"avt_T6": 234.0}
u24 = {"u24_T6": 8.5}
```

После build:

```python
state.avt_telemetry["avt_T6"] == 234.0
state.unit_242000_telemetry["u24_T6"] == 8.5
```

---

# 6. FIX №2 — УБРАТЬ ДВЕ FEATURE PIPELINES

Сейчас:

```text
training:
src/feature_service/features.py

runtime:
src/feature_service/runtime_buffer.py
```

содержат разные наборы:

```text
KEY_COLS
missing flags
rolling logic
domain features
fill strategy
```

Это training-serving skew.

Нужно создать один общий компонент.

---

# 7. СОЗДАТЬ `FeatureTransformer`

Предпочтительно:

```text
src/feature_service/transformer.py
```

Класс или набор pure functions:

```python
FeatureTransformer
```

Он должен содержать:

```text
key column selection
lag features
rolling features
delta
delta6
slope
missing flags
domain features
fill policy
infinity handling
feature ordering helpers
```

---

# 8. TRAINING И RUNTIME ДОЛЖНЫ ИСПОЛЬЗОВАТЬ ОДИН `FeatureTransformer`

Training:

```text
raw merged dataframe
    ↓
FeatureTransformer.transform(...)
    ↓
training matrix
```

Runtime:

```text
history dataframe
    ↓
FeatureTransformer.transform(...)
    ↓
latest feature row
```

Нельзя дублировать formulas.

---

# 9. НЕ МЕНЯТЬ СУЩЕСТВУЮЩИЕ MODEL WEIGHTS

Рефакторинг feature pipeline должен воспроизводить текущую feature schema существующей модели.

То есть необходимо восстановить фактическую training feature logic, на которой были обучены существующие artifacts.

Не менять смысл признаков.

---

# 10. СРАВНИТЬ RUNTIME FEATURE SCHEMA С MODEL ARTIFACT

Использовать:

```python
expected_features = quality_agent.model_metadata.feature_names
```

Проверить:

```text
expected_count
actual_count
missing
extra
order
```

---

# 11. FIX №3 — KEY_COLS ДОЛЖНЫ БЫТЬ ЕДИНЫМИ

Сейчас runtime и training используют разные key columns.

Нужно вынести единственную константу:

```text
FEATURE_KEY_COLUMNS
```

в shared config/module.

Например:

```text
src/feature_service/feature_spec.py
```

---

# 12. НЕ ДЕРЖАТЬ `KEY_COLS` В ДВУХ ФАЙЛАХ

Удалить дублирование:

```python
KEY_COLS = ...
```

из runtime_buffer, если оно уже определено в shared spec.

---

# 13. FIX №4 — MISSING FLAGS ДОЛЖНЫ СОВПАДАТЬ

Training сейчас может создавать missing flags только для:

```text
key_cols[:20]
```

Runtime не должен создавать другой набор.

Использовать одну и ту же функцию:

```python
add_missing_flags(...)
```

---

# 14. FIX №5 — FILL POLICY ДОЛЖНА БЫТЬ ОДИНАКОВОЙ

Training применял:

```text
ffill()
then fillna(0)
```

Runtime сейчас может делать:

```text
fillna(0)
```

Это неприемлемо.

Вынести единую preprocessing policy:

```python
apply_missing_value_policy(...)
```

Если training действительно использовал:

```python
ffill().fillna(0)
```

runtime должен использовать тот же подход.

---

# 15. НЕ ПОДМЕНЯТЬ КРИТИЧЕСКИЕ FEATURE НУЛЯМИ БЕЗ КОНТЕКСТА

Если конкретный feature отсутствует полностью в runtime history:

```text
column not observed at all
```

это не то же самое, что:

```text
NaN inside observed column
```

Правило:

```text
expected column absent entirely
→ schema unavailable
→ ABSTAIN
```

А preprocessing fill использовать только внутри существующей колонки.

---

# 16. FIX №6 — `RuntimeFeatureBuffer.feature_ready`

Сейчас:

```python
feature_ready = history_size >= 36
```

недостаточно.

36 строк не обязательно означают 6 часов истории.

---

# 17. READINESS ДОЛЖЕН УЧИТЫВАТЬ ВРЕМЕННОЕ ПОКРЫТИЕ

Добавить:

```python
history_duration_minutes
```

и проверять:

```text
history_duration >= required_history_minutes
```

---

# 18. ПРОВЕРИТЬ SAMPLING COVERAGE

Если ожидается 10-минутный шаг:

```text
6 часов ≈ 36 интервалов
```

Проверять:

```text
duplicates
large gaps
too sparse history
```

Не обязательно жёстко требовать идеально 10 минут, но должен быть минимальный coverage threshold.

---

# 19. ВВЕСТИ `model_feature_ready`

Отделить:

```text
history_ready
```

от:

```text
model_feature_ready
```

Например:

```python
history_ready
schema_ready
model_feature_ready = history_ready and schema_ready
```

---

# 20. `/ready` ДОЛЖЕН ПОКАЗЫВАТЬ ЭТИ СТАТУСЫ

Ответ:

```json
{
  "quality_model_ready": true,
  "history_ready": true,
  "runtime_schema_ready": true,
  "prediction_ready": true,
  "surrogate_ready": false,
  "optimization_ready": false
}
```

---

# 21. FIX №7 — `/model/info` НЕ ДОЛЖЕН ПУТАТЬ HISTORY И FEATURES

Сейчас `runtime_feature_count` может быть равен `history_size`.

Исправить.

Нужно отдавать:

```text
model_feature_count
runtime_feature_count
history_size
history_duration_minutes
missing_feature_count
schema_match
```

---

# 22. FIX №8 — QUALITY SOURCE RESOLVER РЕАЛЬНО ИНТЕГРИРОВАТЬ

Сейчас resolver создан, но runtime его не использует.

Исправить.

До StateBuilder собрать candidates для каждого indicator.

Например sulfur:

```python
candidates = [
    QualitySourceCandidate(... LIMS ...),
    QualitySourceCandidate(... PAK ...),
    QualitySourceCandidate(... VAK ...),
]
```

---

# 23. RESOLVE BEFORE BUILDING `state.quality`

Сделать:

```text
raw candidate sources
    ↓
QualitySourceResolver.resolve()
    ↓
ResolvedQuality
    ↓
QualitySignal
    ↓
state.quality
```

Не позволять StateBuilder автоматически переписывать PAK значением LIMS по порядку кода.

---

# 24. SOURCE PRIORITY

Использовать явный config:

```text
LIMS priority=1
PAK priority=2
VAK priority=3
```

и freshness.

---

# 25. ЕСЛИ ВСЕ SOURCES STALE

Для критического indicator:

```text
resolved_quality = None
```

Data Quality Agent должен получить:

```text
no valid sulfur source
```

и optimization должен быть запрещён.

---

# 26. QUALITYSOURCE RESOLVER ДОЛЖЕН БЫТЬ ЕДИНСТВЕННЫМ МЕСТОМ ВЫБОРА ИСТОЧНИКА

Не должно быть параллельной логики:

```text
StateBuilder выбирает источник
+
Resolver выбирает источник
```

StateBuilder должен только принимать уже resolved quality.

---

# 27. FIX №9 — ДВА РАЗНЫХ `SurrogateModel`

Сейчас создаются два экземпляра:

```python
OptimizationAgent(surrogate=SurrogateModel())
_agents["surrogate"] = SurrogateModel()
```

Это ошибка.

Создать один:

```python
surrogate = SurrogateModel(...)
```

и дальше:

```python
_agents["surrogate"] = surrogate
_agents["optimization"] = OptimizationAgent(
    surrogate=surrogate,
    ...
)
```

---

# 28. `/ready` И OPTIMIZER ДОЛЖНЫ СМОТРЕТЬ НА ОДИН И ТОТ ЖЕ SURROGATE

Добавить test:

```python
assert _agents["optimization"].surrogate is _agents["surrogate"]
```

---

# 29. FIX №10 — SURROGATE CONTROL MAPPING FAIL-CLOSED

Сейчас action с unmapped control может silently игнорироваться.

Нельзя.

Если action содержит:

```text
control_name
```

которого нет в:

```text
control_to_feature_map
```

возвращать:

```python
SimulationResult(
    status="unavailable",
    availability_reason="Unmapped control ..."
)
```

---

# 30. SURROGATE ДОЛЖЕН ПРОВЕРЯТЬ, ЧТО ACTION ФАКТИЧЕСКИ ПРИМЕНЁН

Для каждого control:

```text
requested
→ mapped
→ feature exists
→ value changed/applied
```

Иначе scenario invalid.

---

# 31. FIX №11 — SURROGATE UNCERTAINTY ИЗ CONFIG

Убрать hardcode:

```python
"sulfur_std": 1.5
```

Загружать из:

```text
configs/runtime.yaml
```

Например:

```yaml
quality_uncertainty:
  method: approximate_fixed_std
  sulfur_std: 1.5
```

---

# 32. FIX №12 — `runtime.yaml` ДОЛЖЕН РЕАЛЬНО УПРАВЛЯТЬ RUNTIME

Сейчас config есть, но agents создаются с defaults.

Создать:

```text
RuntimeConfig
```

Например:

```text
src/shared/config/runtime.py
```

---

# 33. ИЗ `runtime.yaml` ЗАГРУЖАТЬ

DataQualityAgent:

```text
max_stale_minutes
min_avt_signals
min_u24_signals
min_data_quality_score
frozen_window
frozen_std_threshold
jump_threshold
```

ReliabilityAgent:

```text
baseline_risk
```

SafetyAgent:

```text
sulfur_limit
max_violation_prob
max_risk_score
max_ood_score
min_data_quality
```

Surrogate:

```text
sulfur_std
```

---

# 34. НЕ ДУБЛИРОВАТЬ CONFIG VALUES В PYTHON DEFAULTS

Defaults можно оставить только как fallback при отсутствии config, но логировать:

```text
runtime config missing → using fallback
```

---

# 35. FIX №13 — COLD START ABSTAIN ДОЛЖЕН ИМЕТЬ `decision_id`

Сейчас early ABSTAIN из feature buffer может возвращать:

```text
decision_id = "N/A"
```

Нельзя.

Даже если Orchestrator ещё не вызван:

```python
decision_id = str(uuid.uuid4())
```

---

# 36. EARLY ABSTAIN ДОЛЖЕН БЫТЬ НОРМАЛЬНОЙ SCHEMA

Возвращать:

```python
AbstainRecommendation(
    decision_id=...,
    timestamp=...,
    reason=...,
    ...
)
```

а не ad-hoc dict.

---

# 37. ВСЕ `/decision` RESPONSES ДОЛЖНЫ ИМЕТЬ ОДИН ФОРМАТ

Например:

```json
{
  "decision_id": "...",
  "recommendation_type": "abstain",
  "data": { ...AbstainRecommendation... }
}
```

или recommendation.

---

# 38. FIX №14 — TIMESTAMP VALIDATION

Сейчас invalid timestamp может молча превращаться в:

```text
datetime.utcnow()
```

Это опасно.

---

# 39. ИСПОЛЬЗОВАТЬ PYDANTIC `datetime`

В `DecisionRequest` лучше сразу:

```python
timestamp: datetime | None = None
avt_timestamp: datetime | None = None
u24_timestamp: datetime | None = None
pak_sulfur_timestamp: datetime | None = None
...
```

Тогда FastAPI сам вернёт:

```text
422
```

для invalid ISO datetime.

---

# 40. НЕ ИСПОЛЬЗОВАТЬ `except: return None`

Удалить тихий parser.

---

# 41. ЗАПРЕТИТЬ БУДУЩИЕ SOURCE TIMESTAMPS БЕЗ ЯВНОЙ POLICY

Если:

```text
measurement_timestamp > state.timestamp
```

это подозрительно.

Для runtime:

```text
future source timestamp
→ data quality warning / reject
```

---

# 42. FIX №15 — DATA QUALITY HISTORY

Убедиться, что state содержит canonical keys.

После исправления StateBuilder:

```text
avt_T6
u24_T6
```

DataQuality history больше не должна сталкиваться.

---

# 43. ДОБАВИТЬ INTERNAL ASSERTION/VALIDATION

Можно добавить helper:

```python
validate_canonical_state(state)
```

который проверяет:

```text
all AVT keys start with "avt_"
all U24 keys start with "u24_"
```

---

# 44. FIX №16 — RELIABILITY НЕ ДОЛЖЕН DOUBLE-PREFIX

Проверить текущую логику.

Если state уже canonical:

```text
avt_T1
```

она должна остаться:

```text
avt_T1
```

а не:

```text
avt_avt_T1
```

---

# 45. RELIABILITY ASSESSMENT ДОПОЛНИТЬ AVAILABILITY FLAGS

Желательно:

```text
operating_envelope_available
history_ready
```

Чтобы dashboard понимал, когда risk — лишь baseline proxy.

---

# 46. FIX №17 — SAFETY MAX_STEP

После исправления StateBuilder current values должны быть доступны.

Добавить integration test через `/decision` или `/safety/check`, где:

```text
current avt_T1=130
candidate=150
max_step=5
```

→ reject.

---

# 47. MAX_RATE_OF_CHANGE

Если `max_rate_of_change` задан и history доступна:

проверять.

Если нет достаточной history:

```text
rate check unavailable
```

и использовать conservative policy.

---

# 48. FIX №18 — OPTIMIZER ZERO-STD

Проверить:

```python
norm.cdf(... scale=std)
```

Если:

```text
std <= 0
```

не вызывать scipy с некорректным scale.

В таком случае scenario:

```text
simulation_status="error"
```

или reject.

---

# 49. OPTIMIZER ДОЛЖЕН ВОЗВРАЩАТЬ ЯВНЫЙ STATUS ПРИ ОТСУТСТВИИ CANDIDATES

Не просто:

```python
[]
```

Лучше structured result:

```python
CandidateGenerationResult(
    status="unavailable",
    reason="No current controllable variables",
    candidates=[]
)
```

Если не хочешь менять schema сильно — хотя бы Orchestrator должен различать:

```text
no candidates
```

от:

```text
surrogate unavailable
```

---

# 50. FIX №19 — `NO CHANGE` ВСЕГДА ДОЛЖЕН БЫТЬ BASELINE ПРИ ДОСТУПНЫХ CONTROLS

Тест:

```text
candidate[0] == current controls
```

---

# 51. FIX №20 — MODEL INFO ДОЛЖЕН ПОКАЗЫВАТЬ REAL SCHEMA STATUS

Добавить:

```json
{
  "model_feature_count": 721,
  "runtime_feature_count": 721,
  "missing_feature_count": 0,
  "extra_feature_count": 0,
  "schema_match": true,
  "history_size": 40,
  "history_duration_minutes": 390
}
```

---

# 52. FIX №21 — END-TO-END FEATURE PARITY TEST

Это один из самых важных тестов.

Нужно взять исторический кусок данных и на одной и той же timestamp точке:

```text
A) построить features через batch training pipeline
B) построить features через RuntimeFeatureBuffer
```

Сравнить значения по всем feature names существующей модели.

---

# 53. PARITY TEST НЕ ДОЛЖЕН ОБУЧАТЬ МОДЕЛЬ

Использовать:

```text
existing data
existing model feature_names
```

Никакого `.fit()`.

---

# 54. FEATURE PARITY CRITERIA

Для float:

```python
np.isclose(
    batch_feature,
    runtime_feature,
    rtol=...,
    atol=...
)
```

Для всех 721 features.

Допустимые tolerance задокументировать.

---

# 55. ЕСЛИ PARITY TEST НЕ ПРОХОДИТ

Не скрывать.

Найти причину:

```text
lag
rolling
fill policy
source alignment
column selection
domain feature
missing flag
slope
```

Исправить shared transformer.

---

# 56. FIX №22 — HTTP END-TO-END TEST ПОСЛЕ WARMUP

Не достаточно тестировать только:

```text
/health
/ready
```

Нужно:

1. создать TestClient;
2. прогреть `/decision` последовательными 10-минутными точками;
3. после достаточной history вызвать ещё одну точку;
4. проверить:
   - state не пустой;
   - feature schema готова;
   - Quality Agent не падает по schema mismatch.

---

# 57. ПОКА SURROGATE UNAVAILABLE — ОЖИДАЕМЫЙ РЕЗУЛЬТАТ ПОСЛЕ WARMUP

Нормальное поведение:

```text
Quality prediction works
Reliability works
Optimization blocked because surrogate unavailable
→ AbstainRecommendation(
    reason="Surrogate unavailable..."
)
```

Это уже хороший runtime milestone.

---

# 58. ДОБАВИТЬ TEST НА QUALITY INFERENCE AFTER WARMUP

Проверить, что после достаточной history:

```text
quality_pred.model_available == True
prediction is not None
```

если existing model artifact доступен.

---

# 59. FIX №23 — QUALITY SOURCE RESOLUTION TEST НА REAL STATE

Не только unit resolver test.

Проверить runtime:

```text
fresh LIMS + fresh PAK
→ state.quality["sulfur"].source == "LIMS"
```

И:

```text
stale LIMS + fresh PAK
→ source == "PAK"
```

---

# 60. FIX №24 — FUTURE TIMESTAMP TEST

Input:

```text
pak_timestamp > decision_timestamp
```

должен привести к:

```text
422
```

или explicit ABSTAIN/data quality warning.

Не silently age < 0.

---

# 61. FIX №25 — CONFIG TEST

Проверить, что изменение:

```yaml
safety:
  max_violation_prob: 0.15
```

реально меняет `SafetyAgent.max_violation_prob`.

То же для:

```text
DataQualityAgent
ReliabilityAgent
Surrogate uncertainty
```

---

# 62. FIX №26 — НЕ СОЗДАВАТЬ ORCHESTRATOR НА КАЖДЫЙ REQUEST, ЕСЛИ НЕ НУЖНО

Сейчас можно создать singleton Orchestrator после инициализации всех agents.

Это упростит lifecycle и traceability.

Если controls статичны — они могут быть переданы один раз.

---

# 63. ЕСЛИ ORCHESTRATOR СОЗДАЁТСЯ SINGLETON

Убедиться, что:

```text
DataQualityAgent history
ReliabilityAgent history
RuntimeFeatureBuffer
```

также singleton и не сбрасываются между request.

---

# 64. FIX №27 — RESET ENDPOINT ТОЛЬКО ДЛЯ DEMO/TEST

Можно добавить:

```text
POST /runtime/reset
```

только для локальной demo/test среды.

Он очищает:

```text
feature buffer
data quality history
reliability history
```

Не включать его в production mode без защиты.

---

# 65. FIX №28 — REPORT ДОЛЖЕН БЫТЬ ЧЕСТНЫМ

Создать:

```text
reports/runtime_fix_v4.md
```

Не писать:

```text
full runtime working
```

если surrogate всё ещё unavailable.

---

# 66. REPORT: ОБЯЗАТЕЛЬНЫЕ РАЗДЕЛЫ

```text
Implemented
Fixed bugs
Feature parity
Runtime readiness
Quality source resolution
Config integration
Safety
Tests
Known limitations
Next phase
```

---

# 67. ОБНОВИТЬ `runtime_fix_v3.md` НЕ НУЖНО

Создать новый v4 report, чтобы история изменений сохранялась.

---

# 68. ТЕСТЫ — МИНИМАЛЬНЫЙ НАБОР

Обязательно должны быть:

```text
StateBuilder preserves canonical telemetry
AVT/U24 no collision
RuntimeFeatureBuffer history duration readiness
batch/runtime feature parity
full model schema match
QualitySourceResolver integrated
fresh LIMS beats fresh PAK
stale LIMS falls back to PAK
future timestamp rejected
same Surrogate instance
unmapped control → surrogate unavailable
runtime.yaml values applied
early ABSTAIN gets UUID
Recommendation confidence=None
Safety max_step
Safety max_rate if available
Optimizer std<=0 handling
NO CHANGE baseline
HTTP warmup flow
Quality inference after warmup
```

---

# 69. НЕ ПЕРЕХОДИТЬ К МИКРОСЕРВИСАМ ДО ЭТИХ ТЕСТОВ

Microservices начнутся только после того, как:

```text
feature parity ✅
state runtime ✅
quality prediction after warmup ✅
resolver integration ✅
safety current values ✅
config runtime ✅
```

---

# 70. НЕ ДОБАВЛЯТЬ ПОКА PROMETHEUS/GRAFANA

Monitoring будет следующим этапом.

Сейчас priority:

```text
correct runtime
> feature parity
> safety
> tests
> microservices
> observability
```

---

# 71. DEFINITION OF DONE

MVP4 считается готовым, если выполняется всё ниже:

1. `StateBuilder` больше не создаёт пустую telemetry.
2. Runtime state сохраняет canonical AVT/U24 keys.
3. Training и runtime используют один FeatureTransformer.
4. KEY_COLS едины.
5. Missing flags едины.
6. Fill policy едина.
7. Batch/runtime feature parity test проходит.
8. Runtime строит exact model feature schema.
9. `feature_ready` учитывает duration/coverage, а не только count.
10. QualitySourceResolver реально интегрирован.
11. LIMS/PAK/VAK resolution работает по priority+freshness.
12. Один Surrogate instance используется в API и Optimizer.
13. Unmapped controls в surrogate fail-closed.
14. runtime.yaml реально применяется к агентам.
15. sulfur_std не hardcoded в surrogate.
16. Early ABSTAIN имеет UUID и нормальную schema.
17. Invalid timestamps не подменяются silently.
18. `/model/info` показывает корректные counts/status.
19. Safety видит реальные current control values.
20. HTTP warmup test проходит.
21. Quality inference после warmup проходит.
22. Никакая модель не обучалась.
23. Surrogate unavailable корректно приводит к ABSTAIN, если реальной surrogate модели пока нет.
24. Создан `reports/runtime_fix_v4.md`.

---

# 72. ПОРЯДОК РАБОТЫ

Работать строго в таком порядке:

```text
1. StateBuilder runtime fix
2. shared FeatureTransformer
3. training/runtime feature parity
4. RuntimeFeatureBuffer readiness
5. QualitySourceResolver integration
6. single Surrogate instance
7. surrogate fail-closed mappings
8. runtime.yaml integration
9. timestamp validation
10. proper early ABSTAIN schema
11. model info correctness
12. Safety current/max_step/rate
13. HTTP warmup integration test
14. quality inference after warmup
15. runtime_fix_v4.md
```

---

# 73. НАЧНИ СЕЙЧАС

Не обучай модели.

Не добавляй новые микросервисы.

Не добавляй Grafana.

Сначала добейся, чтобы текущий in-process runtime:

```text
historical/replay input
→ shared feature pipeline
→ exact existing model schema
→ real quality inference
→ safe ABSTAIN on unavailable surrogate
```

работал корректно и воспроизводимо.
