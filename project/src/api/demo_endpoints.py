#!/usr/bin/env python3
"""Интеграция demo replay в API для запуска из UI."""
from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEMO_SCRIPT = PROJECT_ROOT / "scripts" / "demo_replay.py"

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/demo", tags=["demo"])

# Активные demo replay процессы
_active_replays: dict[str, subprocess.Popen] = {}


class DemoReplayStatus(BaseModel):
    replay_id: str
    scenario: str
    speed: float
    status: Literal["running", "completed", "failed"]
    pid: int | None = None


@router.post("/replay/start")
async def start_demo_replay(
    scenario: Literal["normal", "exceedance"] = Query(..., description="Demo scenario to replay"),
    speed: float = Query(default=100.0, gt=0, le=500, description="Replay speed multiplier"),
    # identity: Identity = Depends(engineer_access),  # Раскомментировать для production
) -> DemoReplayStatus:
    """Запустить demo replay в фоновом режиме."""

    if not DEMO_SCRIPT.exists():
        raise HTTPException(status_code=503, detail=f"Demo script not found: {DEMO_SCRIPT}")

    replay_id = str(uuid.uuid4())[:8]

    try:
        # Запустить demo_replay.py в фоне
        process = subprocess.Popen(
            [
                sys.executable,
                str(DEMO_SCRIPT),
                "--scenario", scenario,
                "--speed", str(speed),
                "--api-url", "http://localhost:8000",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=PROJECT_ROOT,
        )

        _active_replays[replay_id] = process

        logger.info(f"Started demo replay {replay_id}: scenario={scenario}, speed={speed}, pid={process.pid}")

        return DemoReplayStatus(
            replay_id=replay_id,
            scenario=scenario,
            speed=speed,
            status="running",
            pid=process.pid,
        )

    except Exception as e:
        logger.error(f"Failed to start demo replay: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start replay: {e}")


@router.get("/replay/{replay_id}/status")
async def get_replay_status(replay_id: str) -> DemoReplayStatus:
    """Получить статус demo replay."""

    if replay_id not in _active_replays:
        raise HTTPException(status_code=404, detail=f"Replay {replay_id} not found")

    process = _active_replays[replay_id]
    poll = process.poll()

    if poll is None:
        status = "running"
    elif poll == 0:
        status = "completed"
    else:
        status = "failed"

    return DemoReplayStatus(
        replay_id=replay_id,
        scenario="unknown",  # Можно хранить в отдельном dict
        speed=100.0,
        status=status,
        pid=process.pid if poll is None else None,
    )


@router.post("/replay/{replay_id}/stop")
async def stop_replay(replay_id: str) -> dict:
    """Остановить активный demo replay."""

    if replay_id not in _active_replays:
        raise HTTPException(status_code=404, detail=f"Replay {replay_id} not found")

    process = _active_replays[replay_id]

    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()

    del _active_replays[replay_id]

    return {"replay_id": replay_id, "status": "stopped"}


@router.get("/scenarios")
async def list_scenarios() -> dict:
    """Список доступных demo сценариев."""

    return {
        "scenarios": [
            {
                "id": "normal",
                "name": "Нормальный режим",
                "description": "Q21 стабильно ниже 10 ppm, MAE < 2.0",
                "period": "2023-06-15 08:00 — 12:00",
                "expected_q21_range": [7.5, 9.5],
            },
            {
                "id": "exceedance",
                "name": "Риск превышения Q21",
                "description": "Q21 растёт и приближается к 10 ppm",
                "period": "2023-08-22 14:00 — 18:00",
                "expected_q21_range": [9.0, 11.5],
            },
        ]
    }


# Для подключения к основному app.py:
# from src.api.demo_endpoints import router as demo_router
# app.include_router(demo_router)
