#!/usr/bin/env python3
"""Preflight проверка перед презентацией.

Проверяет доступность всех критических компонентов системы:
- API gateway
- PostgreSQL
- Redis
- Модели ML
- Grafana (опционально)
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("preflight")

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class PreflightCheck:
    """Preflight проверки системы."""

    def __init__(self, api_url: str, api_key: str | None = None, skip_optional: bool = False):
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.skip_optional = skip_optional
        self.results: dict[str, dict[str, Any]] = {}

    def check_api_health(self) -> bool:
        """Проверка health endpoint API."""
        logger.info("Проверка API health...")
        try:
            response = httpx.get(f"{self.api_url}/health", timeout=5)
            response.raise_for_status()
            data = response.json()
            self.results["api_health"] = {
                "status": "ok",
                "response": data,
                "latency_ms": response.elapsed.total_seconds() * 1000,
            }
            logger.info(f"✓ API health: {data.get('status', 'unknown')}")
            return True
        except Exception as e:
            self.results["api_health"] = {"status": "error", "error": str(e)}
            logger.error(f"✗ API health failed: {e}")
            return False

    def check_api_ready(self) -> bool:
        """Проверка готовности модели и runtime."""
        logger.info("Проверка API /ready...")
        try:
            headers = {"X-API-Key": self.api_key} if self.api_key else {}
            response = httpx.get(f"{self.api_url}/ready", headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()

            self.results["api_ready"] = {
                "status": "ok",
                "ready": data.get("ready", False),
                "details": data,
            }

            if data.get("ready"):
                logger.info("✓ Runtime полностью готов")
            else:
                logger.warning(f"⚠ Runtime не готов: {data}")
                for key, value in data.items():
                    if key.endswith("_ready") and not value:
                        logger.warning(f"  - {key}: {value}")

            return data.get("ready", False)
        except Exception as e:
            self.results["api_ready"] = {"status": "error", "error": str(e)}
            logger.error(f"✗ API /ready failed: {e}")
            return False

    def check_q21_status(self) -> bool:
        """Проверка Q21 shadow pipeline."""
        logger.info("Проверка Q21 status...")
        try:
            headers = {"X-API-Key": self.api_key} if self.api_key else {}
            response = httpx.get(f"{self.api_url}/q21/status", headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()

            self.results["q21_status"] = {
                "status": "ok",
                "ready": data.get("ready", False),
                "details": data,
            }

            if data.get("ready"):
                horizons = data.get("available_horizons_hours", [])
                logger.info(f"✓ Q21 pipeline готов: {len(horizons)} горизонтов")
            else:
                logger.warning(f"⚠ Q21 pipeline не готов: {data.get('error', 'unknown')}")
                missing = data.get("missing_artifacts", [])
                if missing:
                    logger.warning(f"  Отсутствуют артефакты: {', '.join(missing)}")

            return data.get("ready", False)
        except Exception as e:
            self.results["q21_status"] = {"status": "error", "error": str(e)}
            logger.error(f"✗ Q21 status failed: {e}")
            return False

    def check_prometheus_metrics(self) -> bool:
        """Проверка Prometheus metrics endpoint."""
        logger.info("Проверка Prometheus metrics...")
        try:
            response = httpx.get(f"{self.api_url}/metrics", timeout=5)
            response.raise_for_status()
            text = response.text

            # Ищем ключевые метрики
            metrics_found = []
            for metric in ["neftekod_runtime_ready", "neftekod_quality_model_ready", "neftekod_http_requests_total"]:
                if metric in text:
                    metrics_found.append(metric)

            self.results["prometheus_metrics"] = {
                "status": "ok",
                "metrics_found": len(metrics_found),
                "sample_metrics": metrics_found[:5],
            }
            logger.info(f"✓ Prometheus metrics доступны: {len(metrics_found)} ключевых метрик")
            return True
        except Exception as e:
            self.results["prometheus_metrics"] = {"status": "error", "error": str(e)}
            logger.error(f"✗ Prometheus metrics failed: {e}")
            return False

    def check_grafana(self, grafana_url: str) -> bool:
        """Проверка доступности Grafana (опционально)."""
        if self.skip_optional:
            logger.info("Пропуск проверки Grafana (--skip-optional)")
            return True

        logger.info(f"Проверка Grafana на {grafana_url}...")
        try:
            response = httpx.get(f"{grafana_url}/api/health", timeout=5)
            response.raise_for_status()
            data = response.json()

            self.results["grafana"] = {
                "status": "ok",
                "health": data,
            }
            logger.info(f"✓ Grafana доступна: {data.get('database', 'unknown')}")
            return True
        except Exception as e:
            self.results["grafana"] = {"status": "error", "error": str(e)}
            logger.warning(f"⚠ Grafana недоступна: {e}")
            return False

    def check_models_on_disk(self, models_dir: Path) -> bool:
        """Проверка наличия моделей на диске."""
        logger.info(f"Проверка моделей в {models_dir}...")

        try:
            if not models_dir.exists():
                raise FileNotFoundError(f"Директория моделей не найдена: {models_dir}")

            # Основная модель качества
            quality_model = models_dir / "quality_model.pkl"

            # Q21 модели
            q21_models = list(models_dir.glob("q21_h*_model.pkl"))

            models_found = []
            if quality_model.exists():
                models_found.append(str(quality_model.name))

            models_found.extend([m.name for m in q21_models])

            self.results["models_on_disk"] = {
                "status": "ok",
                "models_found": len(models_found),
                "models": models_found,
            }

            logger.info(f"✓ Найдено моделей: {len(models_found)}")
            for model in models_found[:10]:
                logger.info(f"  - {model}")

            return len(models_found) > 0
        except Exception as e:
            self.results["models_on_disk"] = {"status": "error", "error": str(e)}
            logger.error(f"✗ Проверка моделей failed: {e}")
            return False

    def run_all_checks(self, grafana_url: str | None = None, models_dir: Path | None = None) -> bool:
        """Запустить все проверки."""
        logger.info("=" * 60)
        logger.info("PREFLIGHT CHECK — Проверка готовности к презентации")
        logger.info("=" * 60)

        checks = [
            ("API Health", lambda: self.check_api_health()),
            ("API Ready", lambda: self.check_api_ready()),
            ("Q21 Status", lambda: self.check_q21_status()),
            ("Prometheus Metrics", lambda: self.check_prometheus_metrics()),
        ]

        if models_dir:
            checks.append(("Models on Disk", lambda: self.check_models_on_disk(models_dir)))

        if grafana_url and not self.skip_optional:
            checks.append(("Grafana", lambda: self.check_grafana(grafana_url)))

        passed = 0
        failed = 0

        for name, check_fn in checks:
            try:
                if check_fn():
                    passed += 1
                else:
                    failed += 1
            except Exception as e:
                logger.error(f"Критическая ошибка в проверке '{name}': {e}")
                failed += 1

            time.sleep(0.2)  # Небольшая пауза между проверками

        logger.info("=" * 60)
        logger.info(f"ИТОГО: {passed} успешно, {failed} провалено")

        if failed == 0:
            logger.info("✓ ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ — Система готова к презентации")
        elif passed >= len(checks) - 1:
            logger.warning("⚠ СИСТЕМА ЧАСТИЧНО ГОТОВА — Некоторые компоненты недоступны")
        else:
            logger.error("✗ СИСТЕМА НЕ ГОТОВА — Критические компоненты недоступны")

        logger.info("=" * 60)

        return failed == 0

    def save_report(self, output_path: Path):
        """Сохранить отчёт проверок."""
        report = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "api_url": self.api_url,
            "checks": self.results,
        }
        output_path.write_text(json.dumps(report, indent=2))
        logger.info(f"Отчёт сохранён: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Preflight проверка перед презентацией")
    parser.add_argument(
        "--api-url",
        default="http://localhost:8000",
        help="URL API gateway (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--api-key",
        help="Engineer API key",
    )
    parser.add_argument(
        "--grafana-url",
        default="http://localhost:3000",
        help="URL Grafana (default: http://localhost:3000)",
    )
    parser.add_argument(
        "--models-dir",
        type=Path,
        default=PROJECT_ROOT / "models",
        help="Директория с моделями",
    )
    parser.add_argument(
        "--skip-optional",
        action="store_true",
        help="Пропустить опциональные проверки (Grafana)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Сохранить отчёт в JSON",
    )

    args = parser.parse_args()

    checker = PreflightCheck(
        api_url=args.api_url,
        api_key=args.api_key,
        skip_optional=args.skip_optional,
    )

    try:
        success = checker.run_all_checks(
            grafana_url=args.grafana_url,
            models_dir=args.models_dir,
        )

        if args.output:
            checker.save_report(args.output)

        sys.exit(0 if success else 1)

    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)
        sys.exit(2)


if __name__ == "__main__":
    main()
