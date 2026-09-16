"""Run the Redis Streams -> Q21 shadow API bridge."""
from __future__ import annotations

import logging
import os

from src.ingestion.q21_stream import Q21StreamWorker, WorkerConfig

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def main() -> None:
    config = WorkerConfig(
        redis_url=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
        api_url=os.environ.get("NEFTEKOD_API_URL", "http://127.0.0.1:8000"),
        api_key=os.environ.get("NEFTEKOD_ENGINEER_API_KEY"),
        stream=os.environ.get("Q21_SOURCE_STREAM", "telemetry.received"),
        group=os.environ.get("Q21_CONSUMER_GROUP", "q21-shadow"),
        consumer=os.environ.get("Q21_CONSUMER_NAME", "q21-worker-1"),
    )
    logging.info("Starting Q21 stream worker: %s -> %s", config.stream, config.api_url)
    Q21StreamWorker(config).run_forever()


if __name__ == "__main__":
    main()

