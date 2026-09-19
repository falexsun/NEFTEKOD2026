#!/usr/bin/env python3
"""Обновление презентационных цифр после прогона."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def update_presentation_stats(replay_stats_file: Path, output_file: Path):
    """Обновить презентационные цифры на основе последнего replay."""

    if not replay_stats_file.exists():
        print(f"Статистика replay не найдена: {replay_stats_file}")
        sys.exit(1)

    stats = json.loads(replay_stats_file.read_text())

    # Извлечь ключевые метрики
    scenario = stats.get("scenario", "unknown")
    total_points = stats.get("total_points", 0)
    sent = stats.get("sent", 0)
    q21_mean = stats.get("q21_mean")
    q21_min = stats.get("q21_min")
    q21_max = stats.get("q21_max")
    duration = stats.get("duration_seconds", 0)

    # Сформировать презентационный отчёт
    presentation = {
        "last_updated": datetime.utcnow().isoformat(),
        "scenario": scenario,
        "demo_metrics": {
            "total_telemetry_points": sent,
            "time_window_minutes": total_points * 10,
            "replay_duration_seconds": round(duration, 1),
            "speedup_factor": round((total_points * 10 * 60) / duration) if duration > 0 else 0,
        },
        "q21_observed": {
            "mean_ppm": round(q21_mean, 2) if q21_mean else None,
            "min_ppm": round(q21_min, 2) if q21_min else None,
            "max_ppm": round(q21_max, 2) if q21_max else None,
            "exceedance_occurred": q21_max > 10 if q21_max else False,
        },
        "presentation_talking_points": [
            f"Воспроизведено {sent} точек телеметрии за {round(duration, 1)}s",
            f"Временное окно: {total_points * 10} минут реальных данных",
            f"Q21 диапазон: [{round(q21_min, 2) if q21_min else '?'}, {round(q21_max, 2) if q21_max else '?'}] ppm",
            f"Среднее Q21: {round(q21_mean, 2) if q21_mean else '?'} ppm",
            "Превышение 10 ppm обнаружено" if q21_max and q21_max > 10 else "Q21 в пределах нормы",
            f"Ускорение replay: {round((total_points * 10 * 60) / duration)}x" if duration > 0 else "N/A",
        ],
        "system_status": {
            "shadow_pipeline": "active",
            "forecasts_generated": "real-time",
            "metrics_updated": "prometheus",
            "dashboards_live": ["operator_console", "grafana_q21"],
        }
    }

    output_file.write_text(json.dumps(presentation, indent=2, ensure_ascii=False))
    print(f"✓ Презентационные цифры обновлены: {output_file}")
    print(f"\nКлючевые метрики для презентации:")
    for point in presentation["presentation_talking_points"]:
        print(f"  • {point}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Обновить презентационные цифры после replay")
    parser.add_argument(
        "--replay-stats",
        type=Path,
        default=PROJECT_ROOT / "demo_replay_stats.json",
        help="Файл со статистикой replay",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "PRESENTATION_STATS.json",
        help="Выходной файл с презентационными цифрами",
    )

    args = parser.parse_args()
    update_presentation_stats(args.replay_stats, args.output)


if __name__ == "__main__":
    main()
