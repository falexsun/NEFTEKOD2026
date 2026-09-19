#!/usr/bin/env python3
"""Проверка импортов и согласованности модулей."""
import sys
from pathlib import Path

# Добавить корень проекта в PYTHONPATH
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

print("=" * 50)
print("ПРОВЕРКА ИМПОРТОВ И МОДУЛЕЙ")
print("=" * 50)

errors = []
passed = 0

# 1. Проверка базовых импортов API
print("\n[1/6] Проверка базовых API модулей...")
try:
    from src.api.security import Identity, operator_access
    print("✓ src.api.security")
    passed += 1
except Exception as e:
    errors.append(f"✗ src.api.security: {e}")

try:
    from src.api.runtime_store import RuntimeStore
    print("✓ src.api.runtime_store")
    passed += 1
except Exception as e:
    errors.append(f"✗ src.api.runtime_store: {e}")

# 2. Проверка новых модулей
print("\n[2/6] Проверка WebSocket модуля...")
try:
    from src.api.websocket import manager, broadcast_q21_update
    print("✓ src.api.websocket.manager")
    print("✓ src.api.websocket.broadcast_q21_update")
    passed += 2
except Exception as e:
    errors.append(f"✗ src.api.websocket: {e}")

print("\n[3/6] Проверка Timeline модуля...")
try:
    from src.api.timeline import TimelineTracker, get_timeline, TimelineEvent
    print("✓ src.api.timeline.TimelineTracker")
    print("✓ src.api.timeline.get_timeline")
    print("✓ src.api.timeline.TimelineEvent")
    passed += 3
except Exception as e:
    errors.append(f"✗ src.api.timeline: {e}")

print("\n[4/6] Проверка Notifications модуля...")
try:
    from src.api.notifications import TelegramNotifier, get_telegram_notifier
    print("✓ src.api.notifications.TelegramNotifier")
    print("✓ src.api.notifications.get_telegram_notifier")
    passed += 2
except Exception as e:
    errors.append(f"✗ src.api.notifications: {e}")

print("\n[5/6] Проверка Anomaly Detection модуля...")
try:
    from src.inference.anomaly import AnomalyDetector, get_anomaly_detector
    print("✓ src.inference.anomaly.AnomalyDetector")
    print("✓ src.inference.anomaly.get_anomaly_detector")
    passed += 2
except Exception as e:
    errors.append(f"✗ src.inference.anomaly: {e}")

print("\n[6/6] Проверка Optimization модуля...")
try:
    from src.inference.optimization import ScenarioOptimizer, get_scenario_optimizer
    print("✓ src.inference.optimization.ScenarioOptimizer")
    print("✓ src.inference.optimization.get_scenario_optimizer")
    passed += 2
except Exception as e:
    errors.append(f"✗ src.inference.optimization: {e}")

# Проверка инстанцирования
print("\n[Бонус] Проверка инстанцирования...")
try:
    timeline = get_timeline()
    print(f"✓ Timeline инстанцирован: {timeline.event_count} событий")
    passed += 1
except Exception as e:
    errors.append(f"✗ Timeline инстанцирование: {e}")

try:
    notifier = get_telegram_notifier()
    print(f"✓ TelegramNotifier инстанцирован: enabled={notifier.enabled}")
    passed += 1
except Exception as e:
    errors.append(f"✗ TelegramNotifier инстанцирование: {e}")

try:
    detector = get_anomaly_detector()
    print(f"✓ AnomalyDetector инстанцирован: fitted={detector.is_fitted}")
    passed += 1
except Exception as e:
    errors.append(f"✗ AnomalyDetector инстанцирование: {e}")

try:
    optimizer = get_scenario_optimizer()
    print(f"✓ ScenarioOptimizer инстанцирован: n_scenarios={optimizer.n_scenarios}")
    passed += 1
except Exception as e:
    errors.append(f"✗ ScenarioOptimizer инстанцирование: {e}")

# Итоги
print("\n" + "=" * 50)
print("ИТОГИ")
print("=" * 50)
print(f"Успешно: {passed}")
print(f"Провалено: {len(errors)}")

if errors:
    print("\nОшибки:")
    for error in errors:
        print(f"  {error}")
    print("\n❌ ЕСТЬ ПРОБЛЕМЫ С ИМПОРТАМИ")
    sys.exit(1)
else:
    print("\n✅ ВСЕ ИМПОРТЫ РАБОТАЮТ КОРРЕКТНО")
    print("\nМодули согласованы и готовы к использованию.")
    sys.exit(0)
