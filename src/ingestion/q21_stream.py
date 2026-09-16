"""Reliable Redis Streams adapter for the Q21 shadow pipeline."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx
import redis

logger = logging.getLogger(__name__)


class InvalidTelemetryEvent(ValueError):
    """The event cannot be converted to the Q21 API contract."""


def decode_event(raw: str | bytes | dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    event = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(event, dict):
        raise InvalidTelemetryEvent("event must be a JSON object")
    values = event.get("unit_242000_telemetry") or event.get("values")
    timestamp = event.get("source_timestamp") or event.get("timestamp")
    if not isinstance(values, dict) or not timestamp:
        raise InvalidTelemetryEvent("source_timestamp and unit_242000_telemetry are required")
    if "Q21" not in values:
        raise InvalidTelemetryEvent("Q21 is absent in unit_242000_telemetry")
    try:
        q21 = float(values["Q21"])
        process = {str(key): float(value) for key, value in values.items()
                   if key != "Q21" and value is not None}
        avt_values = event.get("avt_telemetry") or {}
        for auxiliary in ("F31", "T33", "T55"):
            if auxiliary in avt_values and avt_values[auxiliary] is not None:
                process[auxiliary] = float(avt_values[auxiliary])
    except (TypeError, ValueError) as exc:
        raise InvalidTelemetryEvent("Q21 and process values must be numeric") from exc
    return {
        "timestamp": timestamp,
        "q21": q21,
        "operating_mode": event.get("u24_mode") or event.get("operating_mode") or "normal",
        "values": process,
    }


@dataclass
class WorkerConfig:
    redis_url: str
    api_url: str
    api_key: str | None = None
    stream: str = "telemetry.received"
    group: str = "q21-shadow"
    consumer: str = "q21-worker-1"
    dead_letter_stream: str = "telemetry.q21.dlq"
    block_ms: int = 5000
    reclaim_after_ms: int = 60_000


class Q21StreamWorker:
    def __init__(self, config: WorkerConfig):
        self.config = config
        self.redis = redis.Redis.from_url(config.redis_url, decode_responses=True)
        headers = {"X-API-Key": config.api_key} if config.api_key else {}
        self.http = httpx.Client(base_url=config.api_url.rstrip("/"), headers=headers, timeout=30)

    def ensure_group(self) -> None:
        try:
            self.redis.xgroup_create(self.config.stream, self.config.group, id="0", mkstream=True)
        except redis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def process(self, message_id: str, fields: dict[str, str]) -> str:
        try:
            payload = decode_event(fields.get("data") or fields)
            response = self.http.post("/q21/telemetry", json=payload,
                                      headers={"X-Request-ID": f"redis-{message_id}"})
            if response.status_code == 409:
                self.redis.xack(self.config.stream, self.config.group, message_id)
                return "duplicate"
            response.raise_for_status()
            self.redis.xack(self.config.stream, self.config.group, message_id)
            return response.json().get("state", "accepted")
        except InvalidTelemetryEvent as exc:
            self.redis.xadd(self.config.dead_letter_stream, {
                "source_stream": self.config.stream, "source_id": message_id,
                "reason": str(exc), "data": fields.get("data", json.dumps(fields)),
            })
            self.redis.xack(self.config.stream, self.config.group, message_id)
            return "dead_letter"

    def recover_pending(self) -> int:
        """Claim messages abandoned by a crashed worker and process them again."""
        claimed = self.redis.xautoclaim(
            self.config.stream, self.config.group, self.config.consumer,
            min_idle_time=self.config.reclaim_after_ms, start_id="0-0", count=100,
        )
        messages = claimed[1] if len(claimed) > 1 else []
        for message_id, fields in messages:
            self.process(message_id, fields)
        return len(messages)

    def run_forever(self) -> None:
        self.ensure_group()
        recovered = self.recover_pending()
        if recovered:
            logger.warning("Recovered %s abandoned Q21 stream messages", recovered)
        while True:
            batches = self.redis.xreadgroup(
                self.config.group, self.config.consumer, {self.config.stream: ">"},
                count=20, block=self.config.block_ms,
            )
            for _, messages in batches:
                for message_id, fields in messages:
                    try:
                        result = self.process(message_id, fields)
                        logger.info("Q21 event %s: %s", message_id, result)
                    except (httpx.HTTPError, redis.RedisError) as exc:
                        # Leave the event pending. It will be reclaimed after the
                        # idle timeout instead of being acknowledged and lost.
                        logger.error("Q21 event %s remains pending: %s", message_id, exc)
