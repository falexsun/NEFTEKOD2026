# Q21 Advisory System - Руководство по использованию

**Версия:** 1.0  
**Дата:** 16 сентября 2026  
**Статус:** Production-like Demo / Shadow Pilot Ready

---

## 1. Обзор системы

Q21 Advisory System — это advisory-система для мониторинга содержания серы в керосине (Q21) с горизонтом прогноза 1 час. Система предназначена для демонстрации на хакатоне и теневого пилота, но **НЕ для автоматического управления установкой**.

### Ключевые возможности

- ✅ Прогноз Q21 на 1 час вперёд (MAE 0,725 ppm, улучшение 14% над persistence)
- ✅ Оценка риска превышения 10 ppm (AP=0,906, AUC=0,959)
- ✅ Детекция состояния установки (normal/shutdown/startup/transition)
- ✅ Проверки качества данных (freshness, frozen sensors, OOD)
- ✅ Интерактивный dashboard с визуализацией
- ✅ Настраиваемый компромисс safety vs false alarms (λ=10 или λ=25)

### Важные ограничения

⚠️ **Система НЕ предназначена для:**
- Автоматической записи уставок в АСУ ТП
- Замены решений технолога
- Гарантированного предотвращения нарушений спецификации

⚠️ **Это observational prediction system:**
- Прогнозирует качество на основе исторических паттернов
- НЕ доказывает причинно-следственные связи
- Требует валидации рекомендаций экспертом

---

## 2. Архитектура системы

```
Телеметрия → State Detector → Quality Gates → Feature Prep
                    ↓              ↓              ↓
              [normal?]    [all passed?]   [features]
                    ↓              ↓              ↓
                    └──────────────┴──────────────┘
                                   ↓
                          Q21 Model Bundle
                        (regression + risk)
                                   ↓
                          Advisory Generator
                                   ↓
                    ┌──────────────┴──────────────┐
                    ↓                             ↓
            Dashboard UI              Scenario Analyzer
                                    (what-if, causal NOT validated)
```

### Компоненты

1. **State Detector** (`state_detector.py`)
   - Определяет режим работы установки
   - Выдаёт `NO_ACTION` для non-normal режимов

2. **Quality Gates** (`quality_gates.py`)
   - Проверка свежести данных (макс. 30 мин)
   - Детекция кода Q21=307 (неисправность анализатора)
   - Детекция замороженных датчиков (>2 ч константы)
   - Проверка нулевых знаменателей (F30)
   - OOD-детекция (выход за training domain)

3. **Model Bundle** (`model_bundle.py`)
   - Regression: `reg_h1_all_plus_q21_history_q50.cbm` (SHA: 95469b4...)
   - Risk: `risk_h1_controls_plus_q21_history_s42.cbm` (SHA: a0ef98b...)
   - Проверка checksums при загрузке

4. **Advisory System** (`advisory_system.py`)
   - Координирует все компоненты
   - Генерирует финальную рекомендацию
   - Оценивает confidence

5. **Dashboard** (`q21_advisory_dashboard.py`)
   - Streamlit UI для демонстрации
   - Интерактивные графики (Plotly)
   - Переключение λ=10/25 на лету

---

## 3. Установка и настройка

### Требования

- Python ≥3.11
- CatBoost ≥1.2.10
- Streamlit, Plotly, pandas, numpy

### Установка

```bash
cd /Users/falexsun/code/Нефтекод/project

# Создать виртуальное окружение (если ещё нет)
python3.11 -m venv .venv
source .venv/bin/activate  # Linux/Mac
# или .venv\Scripts\activate  # Windows

# Установить зависимости
pip install -e .
```

### Проверка моделей

```bash
cd /Users/falexsun/code/Нефтекод/eda/experiments/q21_target_asymmetric_v3_20260915/models

# Проверить наличие моделей
ls -lh *.cbm

# Проверить checksums
shasum -a 256 *.cbm
```

Ожидаемые checksums:
- `reg_h1_all_plus_q21_history_q50.cbm`: `95469b40d8b550fa1dbf16e7faba4ed400c0a9398fe015f8042c00259d478eee`
- `risk_h1_controls_plus_q21_history_s42.cbm`: `a0ef98b61af8ba439260e546da13e787c171f0ec90ebd5c300d6b89d18f3e496`

---

## 4. Запуск dashboard

### Локальный запуск

```bash
cd /Users/falexsun/code/Нефтекод/project

source .venv/bin/activate

streamlit run src/dashboard/q21_advisory_dashboard.py
```

Dashboard откроется автоматически в браузере на `http://localhost:8501`

### Конфигурация

В sidebar dashboard:
- **Risk Penalty (λ)**: выбор между λ=10 (balanced) и λ=25 (safety-oriented)
- **Demo data**: использовать демонстрационные данные

---

## 5. Использование через API

### Программный интерфейс

```python
from pathlib import Path
from src.inference.advisory_system import Q21AdvisorySystem
import pandas as pd

# Инициализация
models_dir = Path("eda/experiments/q21_target_asymmetric_v3_20260915/models")
system = Q21AdvisorySystem(models_dir, lambda_penalty=25)

# Подготовка телеметрии
telemetry = pd.DataFrame({
    'timestamp': pd.date_range(end=pd.Timestamp.now(), periods=12, freq='10min'),
    'Q21': [8.5, 9.0, 9.5, 10.0, 10.5, 11.0, 11.5, 12.0, 12.5, 13.0, 13.5, 14.0],
    'F30': [100.5] * 12,
    'F31': [45.2] * 12,
    'W70': [78.5] * 12,
    'T33': [285.3] * 12,
    'T55': [365.7] * 12,
    # ... другие теги
})

# Генерация advisory
advisory = system.generate_advisory(
    telemetry=telemetry,
    current_q21=8.5
)

# Результат
print(f"State: {advisory.plant_state.value}")
print(f"Q21 forecast: {advisory.q21_forecast_1h:.1f} ppm")
print(f"Risk: {advisory.exceedance_probability:.1%}")
print(f"Action: {advisory.action}")
print(f"Message: {advisory.message}")
```

### Обработка результатов

```python
if advisory.action == "NO_ACTION":
    # Установка в non-normal режиме или validation failures
    print(f"Reason: {advisory.reason_code}")
    if advisory.validation_failures:
        for failure in advisory.validation_failures:
            print(f"- {failure.reason_code}: {failure.message}")

elif advisory.action == "MONITOR":
    # Низкий/средний риск, продолжать мониторинг
    print("Continue normal operation")

elif advisory.action == "INVESTIGATE":
    # Высокий/критический риск
    print(f"Risk level: {advisory.exceedance_risk}")
    print("Review operating conditions")
```

---

## 6. Интерпретация результатов

### Уровни риска

| Риск | Вероятность | Рекомендация | Recall (λ=25) |
|------|-------------|--------------|---------------|
| LOW | < 10% | MONITOR | - |
| MEDIUM | 10-30% | MONITOR | - |
| HIGH | 30-60% | INVESTIGATE | - |
| CRITICAL | > 60% | INVESTIGATE | 97.3% |

### Метрики качества (evaluation 2026)

**Regression (Q21 forecast):**
- MAE h=1: 0,725 ppm (vs 0,844 persistence, +14% improvement)
- MAE h=3: 1,387 ppm (vs 1,443 persistence)
- MAE h=6: 1,735 ppm (vs 1,588 persistence, хуже baseline)

**Classification (risk Q21 > 10 ppm, без кода 307):**
- AP h=1: 0,906 (vs 0,885 persistence)
- AUC h=1: 0,959
- Recall @ λ=25: 97,30% (179 FN из 6 627)
- Precision @ λ=25: 46,54%
- FPR @ λ=25: 31,94%

### Настройка λ (trade-off)

| λ | Use Case | Recall | Precision | FPR | Interpretation |
|---|----------|--------|-----------|-----|----------------|
| 10 | Balanced | 94,53% | 55,81% | 21,39% | Компромисс между safety и false alarms |
| 25 | Safety-oriented | 97,30% | 46,54% | 31,94% | Приоритет на обнаружение всех превышений |

**Для финала рекомендуется λ=25** как safety-oriented сценарий.

### Reason codes NO_ACTION

- `PLANT_STATE_SHUTDOWN`: установка в режиме останова
- `PLANT_STATE_STARTUP`: установка в режиме пуска
- `PLANT_STATE_TRANSITION`: переходный режим
- `PLANT_STATE_UNKNOWN`: состояние неопределено
- `STALE_DATA`: данные устарели (>30 мин)
- `Q21_CODE_307`: Q21 показывает код неисправности 307
- `Q21_MISSING`: значение Q21 отсутствует
- `FROZEN_SENSOR`: обнаружен замороженный датчик
- `ZERO_DENOMINATOR`: нулевое значение в знаменателе (F30)
- `OUT_OF_DISTRIBUTION`: признаки вне training domain
- `FEATURE_PREPARATION_ERROR`: ошибка подготовки признаков
- `INFERENCE_ERROR`: ошибка при inference моделей

---

## 7. Сценарная оптимизация

⚠️ **ВАЖНО: Сценарная оптимизация — это model-based what-if анализ**

Система может показывать сценарные рекомендации, но:
- Это НЕ доказанные причинно-следственные связи
- Основано на исторических корреляциях, не на validated causal model
- **Требует экспертной валидации перед любым действием**
- **НЕ для автоматического управления**

```python
# Пример сценарного анализа (ТОЛЬКО ДЕМОНСТРАЦИЯ)
scenario = system.generate_scenario_recommendation(
    advisory=advisory,
    scenario_controls={"T55": +2.0}  # Гипотетическое изменение
)

print(scenario["warning"])  # MODEL-BASED WHAT-IF SCENARIO
print(scenario["disclaimer"])  # Causal effect not validated
```

Эта функция предназначена для:
- Демонстрации возможностей на хакатоне
- Исследовательского анализа экспертами
- Генерации гипотез для дальнейшей валидации

---

## 8. Тестирование

### Запуск unit tests

```bash
cd /Users/falexsun/code/Нефтекод/project

pytest tests/test_inference.py -v
```

### Тестовые сценарии

1. **Normal operation, low risk**
   - Q21 current: 8.5 ppm
   - Ожидается: MONITOR, risk LOW

2. **Normal operation, high risk**
   - Q21 current: 11.5 ppm
   - Ожидается: INVESTIGATE, risk HIGH/CRITICAL

3. **Q21 code 307**
   - Q21 current: 307.0
   - Ожидается: NO_ACTION, reason Q21_CODE_307

4. **Shutdown state**
   - Все потоки < 0.1
   - Ожидается: NO_ACTION, reason PLANT_STATE_SHUTDOWN

5. **Frozen sensor**
   - F30 = const для 12+ точек
   - Ожидается: NO_ACTION, reason FROZEN_SENSOR

6. **Stale data**
   - Timestamp > 30 мин назад
   - Ожидается: NO_ACTION, reason STALE_DATA

---

## 9. Деплой для хакатона

### Чеклист перед демонстрацией

- [ ] Модели скачаны и checksums проверены
- [ ] Dashboard запускается без ошибок
- [ ] Demo data показывает корректные результаты
- [ ] Все disclaimers видны на UI
- [ ] Переключение λ=10/25 работает
- [ ] Reason codes отображаются корректно

### Сценарий демонстрации (5 минут)

**1. Введение (30 сек)**
- Показать название и позиционирование
- Подчеркнуть: production-like demo, НЕ автоматическое управление

**2. Normal operation, low risk (1 мин)**
- Показать Q21 current = 8.5 ppm
- Forecast = 8.2 ppm
- Risk = 5%, action MONITOR
- Объяснить: система в штатном режиме

**3. Escalating risk (1 мин)**
- Переключить на данные с Q21 = 11.0 ppm
- Показать рост риска до 75%
- Action = INVESTIGATE
- Объяснить: система предупреждает о риске превышения

**4. Lambda trade-off (1 мин)**
- Переключить λ с 25 на 10
- Показать изменение trade-off: recall vs precision
- Объяснить: λ=25 safety-oriented, λ=10 balanced

**5. Safety gates (1 мин)**
- Показать сценарий с Q21=307
- NO_ACTION с объяснением
- Объяснить: система не выдаёт рекомендаций при недостоверных данных

**6. Заключение (30 сек)**
- Готовность к теневому пилоту
- Требуется подтверждение controls и накопление лабораторных данных
- Благодарность жюри

### Ответы на вопросы жюри

**Q: Можно ли использовать для автоматического управления?**
A: Нет. Это observational prediction model. Для автоматического управления требуется:
- Подтверждение causal relationships
- Валидация на пилоте
- Интеграция с safety systems
- Регуляторное одобрение

**Q: Какая точность модели?**
A: MAE 0,725 ppm на горизонте 1 час. Улучшение 14% над persistence baseline. AP=0,906 для детекции риска превышения.

**Q: Сколько данных использовано?**
A: 3,5 года телеметрии (01.01.2023 - 07.08.2026), 189 217 точек с шагом 10 минут. Train до 2025, validation/calibration 2025, evaluation 2026.

**Q: Как система помогает технологу?**
A: Система предупреждает о риске превышения за 1 час, давая время на проверку режима и корректировку. Это advisory tool, не замена решения технолога.

---

## 10. Roadmap дальнейшей разработки

### Для теневого пилота

1. **Feature engineering** - реализация полного pipeline признаков
2. **Continuous monitoring** - подключение к live telemetry stream
3. **Logging & audit trail** - запись всех рекомендаций и actions
4. **Alerting system** - интеграция с notification channels
5. **Model retraining pipeline** - автоматическое переобучение на новых данных

### Для промышленного внедрения

1. **Controls validation** - подтверждение управляющих тегов и их ranges
2. **Causal validation** - A/B тесты или RCT для проверки рекомендаций
3. **Safety interlocks** - интеграция с emergency shutdown systems
4. **Regulatory compliance** - сертификация для критичных систем
5. **Operator training** - обучение персонала работе с системой

---

## 11. Контакты и поддержка

**Разработчик:** NEFTECODE 2026 Team  
**Дата создания:** 16 сентября 2026  
**Репозиторий:** `/Users/falexsun/code/Нефтекод`

**Документация:**
- Handoff: `eda/MASTER_AGENT_HANDOFF.md`
- Q21 Results: `eda/Q21_TARGET_RESULTS.md`
- Findings: `eda/HACKATHON_FINDINGS.md`

---

## Приложение A: Формат AdvisoryRecommendation

```python
@dataclass
class AdvisoryRecommendation:
    timestamp: pd.Timestamp
    plant_state: PlantState  # NORMAL, SHUTDOWN, STARTUP, TRANSITION, UNKNOWN
    q21_current: Optional[float]  # Current Q21 value, ppm
    q21_forecast_1h: Optional[float]  # Forecast +1h, ppm
    exceedance_probability: Optional[float]  # P(Q21 > 10 ppm), 0-1
    exceedance_risk: str  # LOW, MEDIUM, HIGH, CRITICAL
    action: str  # MONITOR, NO_ACTION, INVESTIGATE, ADJUST
    reason_code: str  # OK or specific reason for NO_ACTION
    message: str  # Human-readable explanation
    confidence: str  # HIGH, MEDIUM, LOW, NO_CONFIDENCE
    details: Dict  # Additional context
    validation_failures: List[ValidationResult]  # If any gates failed
```

---

**Версия документа:** 1.0  
**Последнее обновление:** 16.09.2026
