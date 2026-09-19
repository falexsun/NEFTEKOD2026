#!/usr/bin/env python3
"""Добавить кнопку запуска demo replay в инженерный режим."""
import sys
from pathlib import Path

# Этот скрипт будет интегрирован в React интерфейс
# Для хакатона достаточно CLI команд, но можно добавить API endpoint

print("""
Для интеграции demo replay в UI:

1. Добавить API endpoint в src/api/app.py:

@app.post("/demo/replay/{scenario}")
async def start_demo_replay(
    scenario: Literal["normal", "exceedance"],
    speed: float = Query(default=100.0, gt=0, le=500),
    _: Identity = Depends(engineer_access)
):
    # Запустить demo_replay.py в фоне
    import subprocess
    proc = subprocess.Popen([
        sys.executable, "scripts/demo_replay.py",
        "--scenario", scenario,
        "--speed", str(speed),
        "--api-url", "http://localhost:8000"
    ])
    return {"status": "started", "scenario": scenario, "pid": proc.pid}

2. Добавить кнопки в React UI (например, в Settings или Engineer view):

<div className="demo-controls">
  <h3>Демо-сценарии</h3>
  <button onClick={() => startDemoReplay('normal')}>
    Нормальный режим
  </button>
  <button onClick={() => startDemoReplay('exceedance')}>
    Превышение Q21
  </button>
</div>

3. Для хакатона достаточно CLI:

# Терминал 1: запустить систему
./scripts/start_demo.sh

# Терминал 2: запустить демо-сценарий
uv run python scripts/demo_replay.py --scenario normal --speed 100

Или добавить ссылки в README и презентацию.
""")
