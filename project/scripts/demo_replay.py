#!/usr/bin/env python3
"""Демонстрационный сценарий для финала хакатона.

Воспроизводимый replay с двумя сценариями:
1. Нормальный режим (Q21 < 10 ppm)
2. Превышение Q21 (Q21 → 10+ ppm)
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("demo-replay")


# Демонстрационные сценарии с фиксированными временными окнами
DEMO_SCENARIOS = {
    "normal": {
        "name": "Нормальный режим",
        "description": "Q21 стабильно ниже 10 ppm, MAE < 2.0",
        "start": "2023-06-15 08:00",
        "end": "2023-06-15 12:00",
        "expected_q21_range": (7.5, 9.5),
    },
    "exceedance": {
        "name": "Риск превышения Q21",
        "description": "Q21 растёт и приближается к 10 ppm",
        "start": "2023-08-22 14:00",
        "end": "2023-08-22 18:00",
        "expected_q21_range": (9.0, 11.5),
    },
}


def validate_scenario_data(df: pd.DataFrame, scenario_name: str) -> bool:
    """Проверка, что данные соответствуют ожидаемому сценарию."""
    scenario = DEMO_SCENARIOS[scenario_name]
    if "Q21" not in df.columns:
        logger.error("Q21 отсутствует в данных")
        return False

    q21_mean = df["Q21"].mean()
    q21_min = df["Q21"].min()
    q21_max = df["Q21"].max()

    expected_min, expected_max = scenario["expected_q21_range"]

    logger.info(
        f"Сценарий '{scenario['name']}': Q21 range [{q21_min:.2f}, {q21_max:.2f}], "
        f"mean={q21_mean:.2f}, ожидается [{expected_min}, {expected_max}]"
    )

    # Проверяем, что диапазон примерно соответствует
    if q21_min < expected_min - 2.0 or q21_max > expected_max + 2.0:
        logger.warning(
            f"Данные не соответствуют сценарию '{scenario_name}'. "
            f"Replay продолжится, но результаты могут отличаться."
        )

    return True


def replay_demo_scenario(
    scenario_name: str,
    api_url: str,
    api_key: str | None,
    data_dir: Path,
    speed: float = 100.0,
    dry_run: bool = False,
) -> dict:
    """Воспроизвести демонстрационный сценарий."""

    if scenario_name not in DEMO_SCENARIOS:
        raise ValueError(f"Неизвестный сценарий: {scenario_name}. Доступны: {list(DEMO_SCENARIOS.keys())}")

    scenario = DEMO_SCENARIOS[scenario_name]
    logger.info(f"=== ДЕМО-СЦЕНАРИЙ: {scenario['name']} ===")
    logger.info(f"Описание: {scenario['description']}")
    logger.info(f"Период: {scenario['start']} — {scenario['end']}")
    logger.info(f"Скорость: {speed}x")

    # Загрузка данных
    from src.ingestion.loaders import load_avt_tags, load_242000_tags

    avt_path = data_dir / "avt_tags.csv"
    u24_path = data_dir / "242000_tags.csv"

    if not avt_path.exists() or not u24_path.exists():
        raise FileNotFoundError(f"Данные не найдены в {data_dir}")

    logger.info("Загрузка данных...")
    avt_df = load_avt_tags(avt_path)
    u24_df = load_242000_tags(u24_path)

    # Фильтрация по времени
    start_ts = pd.Timestamp(scenario["start"])
    end_ts = pd.Timestamp(scenario["end"])

    avt_slice = avt_df[(avt_df.index >= start_ts) & (avt_df.index <= end_ts)]
    u24_slice = u24_df[(u24_df.index >= start_ts) & (u24_df.index <= end_ts)]

    if len(u24_slice) == 0:
        raise ValueError(f"Нет данных 24-2000 в период {start_ts} — {end_ts}")

    # Валидация сценария
    validate_scenario_data(u24_slice, scenario_name)

    timestamps = sorted(set(avt_slice.index) | set(u24_slice.index))
    logger.info(f"Найдено {len(timestamps)} временных точек для replay")

    # HTTP клиент
    headers = {"X-API-Key": api_key} if api_key else {}
    api_client = httpx.Client(base_url=api_url.rstrip("/"), headers=headers, timeout=30) if not dry_run else None

    # Статистика
    stats = {
        "scenario": scenario_name,
        "total_points": len(timestamps),
        "sent": 0,
        "skipped": 0,
        "errors": 0,
        "start_time": time.time(),
        "q21_values": [],
    }

    logger.info(f"Начало replay сценария '{scenario_name}'...")

    for i, ts in enumerate(timestamps):
        # Подготовка payload
        payload = {
            "timestamp": ts.isoformat(),
            "operating_mode": "normal",
            "ingestion_mode": "replay",
        }

        # AVT данные
        avt_values = {}
        if ts in avt_slice.index:
            row = avt_slice.loc[ts]
            avt_values = {col: float(row[col]) for col in avt_slice.columns if pd.notna(row[col])}

        # 24-2000 данные
        if ts not in u24_slice.index:
            stats["skipped"] += 1
            continue

        row = u24_slice.loc[ts]
        u24_values = {col: float(row[col]) for col in u24_slice.columns if pd.notna(row[col])}

        if "Q21" not in u24_values:
            logger.warning(f"Пропуск {ts}: Q21 отсутствует")
            stats["skipped"] += 1
            continue

        q21_value = u24_values.pop("Q21")
        payload["q21"] = q21_value
        payload["values"] = {**u24_values, **avt_values}

        stats["q21_values"].append(q21_value)

        # Отправка
        if dry_run:
            if i < 3:
                logger.info(f"[DRY-RUN] {ts}: Q21={q21_value:.2f}, signals={len(payload['values'])}")
        else:
            try:
                response = api_client.post(
                    "/q21/telemetry",
                    json=payload,
                    headers={"X-Request-ID": f"demo-{scenario_name}-{ts.isoformat()}"},
                )
                if response.status_code == 409:
                    # Дубликат — нормально для повторного запуска
                    pass
                else:
                    response.raise_for_status()
                stats["sent"] += 1
            except Exception as e:
                logger.error(f"Ошибка отправки {ts}: {e}")
                stats["errors"] += 1

        # Задержка для имитации реального времени
        if speed > 0 and i < len(timestamps) - 1:
            interval = (timestamps[i + 1] - ts).total_seconds() / speed
            time.sleep(min(interval, 0.5))

        # Прогресс
        if (i + 1) % 10 == 0 or i == len(timestamps) - 1:
            progress = (i + 1) / len(timestamps) * 100
            logger.info(f"Прогресс: {i + 1}/{len(timestamps)} ({progress:.1f}%)")

    stats["duration_seconds"] = time.time() - stats["start_time"]
    stats["q21_mean"] = sum(stats["q21_values"]) / len(stats["q21_values"]) if stats["q21_values"] else None
    stats["q21_min"] = min(stats["q21_values"]) if stats["q21_values"] else None
    stats["q21_max"] = max(stats["q21_values"]) if stats["q21_values"] else None

    logger.info("=" * 60)
    logger.info(f"✓ Сценарий '{scenario['name']}' завершён")
    logger.info(f"Отправлено: {stats['sent']}/{stats['total_points']}, ошибок: {stats['errors']}")
    logger.info(f"Q21: [{stats['q21_min']:.2f}, {stats['q21_max']:.2f}], среднее {stats['q21_mean']:.2f}")
    logger.info(f"Время: {stats['duration_seconds']:.1f}s")
    logger.info("=" * 60)

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Демонстрационный replay для финала хакатона",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Доступные сценарии:
  normal      — Нормальный режим (Q21 < 10 ppm)
  exceedance  — Превышение Q21 (Q21 → 10+ ppm)

Пример:
  python scripts/demo_replay.py --scenario normal --api-url http://localhost:8000
  python scripts/demo_replay.py --scenario exceedance --speed 200 --dry-run
        """,
    )
    parser.add_argument(
        "--scenario",
        required=True,
        choices=list(DEMO_SCENARIOS.keys()),
        help="Демо-сценарий",
    )
    parser.add_argument(
        "--api-url",
        default="http://localhost:8000",
        help="URL API (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Engineer API key",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=100.0,
        help="Скорость replay (default: 100x)",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=PROJECT_ROOT.parent / "data",
        help="Директория с данными",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Не отправлять данные, только показать",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Сохранить статистику в JSON",
    )

    args = parser.parse_args()

    try:
        stats = replay_demo_scenario(
            scenario_name=args.scenario,
            api_url=args.api_url,
            api_key=args.api_key,
            data_dir=args.data_dir,
            speed=args.speed,
            dry_run=args.dry_run,
        )

        if args.output:
            args.output.write_text(json.dumps(stats, indent=2, default=str))
            logger.info(f"Статистика сохранена в {args.output}")

    except Exception as e:
        logger.error(f"Ошибка: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
