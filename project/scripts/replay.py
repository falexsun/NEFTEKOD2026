"""Historical replay — publishes historical data to Redis Streams as if realtime.

Usage:
    uv run python scripts/replay.py --start "2023-06-01 08:00" --end "2023-06-01 20:00" --speed 100
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd
import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("replay")


def main():
    parser = argparse.ArgumentParser(description="Historical data replay")
    parser.add_argument("--start", required=True, help="Start timestamp (YYYY-MM-DD HH:MM)")
    parser.add_argument("--end", required=True, help="End timestamp (YYYY-MM-DD HH:MM)")
    parser.add_argument("--speed", type=float, default=1.0, help="Speed multiplier (100 = 100x realtime)")
    parser.add_argument("--redis-url", default="redis://localhost:6379", help="Redis URL")
    parser.add_argument("--api-url", help="Send Q21 directly to this API instead of Redis")
    parser.add_argument("--api-key", default=os.environ.get("NEFTEKOD_ENGINEER_API_KEY"),
                        help="Engineer API key (defaults to NEFTEKOD_ENGINEER_API_KEY)")
    default_data = PROJECT_ROOT.parent / "data" if (PROJECT_ROOT.parent / "data").exists() else PROJECT_ROOT / "data"
    parser.add_argument("--data-dir", default=str(default_data), help="Data directory")
    parser.add_argument("--dry-run", action="store_true", help="Print events without sending to Redis")
    args = parser.parse_args()

    start_ts = pd.Timestamp(args.start)
    end_ts = pd.Timestamp(args.end)
    speed = args.speed

    data_dir = Path(args.data_dir)
    avt_path = data_dir / "avt_tags.csv"
    u24_path = data_dir / "242000_tags.csv"

    if not avt_path.exists():
        logger.error(f"AVT data file not found: {avt_path}")
        return
    if not u24_path.exists():
        logger.error(f"24-2000 data file not found: {u24_path}")
        return

    # Load data
    logger.info("Loading data...")
    from src.ingestion.loaders import load_avt_tags, load_242000_tags
    avt_df = load_avt_tags(avt_path)
    u24_df = load_242000_tags(u24_path)

    # Filter to time range
    avt_slice = avt_df[(avt_df.index >= start_ts) & (avt_df.index <= end_ts)]
    u24_slice = u24_df[(u24_df.index >= start_ts) & (u24_df.index <= end_ts)]

    logger.info(f"Replay range: {start_ts} – {end_ts}")
    logger.info(f"AVT records: {len(avt_slice)}, 24-2000 records: {len(u24_slice)}")

    if len(avt_slice) == 0:
        logger.warning("No data in the specified time range!")
        return

    # Connect to Redis
    redis_client = None
    api_client = None
    if args.api_url and not args.dry_run:
        headers = {"X-API-Key": args.api_key} if args.api_key else {}
        api_client = httpx.Client(base_url=args.api_url.rstrip("/"), headers=headers, timeout=30)
        logger.info("Direct Q21 API destination: %s", args.api_url)
    elif not args.dry_run:
        try:
            import redis
            redis_client = redis.from_url(args.redis_url)
            redis_client.ping()
            logger.info(f"Connected to Redis: {args.redis_url}")
        except Exception as e:
            logger.warning(f"Redis not available ({e}) — running in dry-run mode")
            redis_client = None

    # Replay loop
    n_events = 0
    timestamps = sorted(set(avt_slice.index) | set(u24_slice.index))

    logger.info(f"Starting replay: {len(timestamps)} timestamps, speed={speed}x")

    for i, ts in enumerate(timestamps):
        # Build event payload
        payload = {
            "event_id": str(uuid.uuid4()),
            "event_type": "telemetry.received",
            "event_timestamp": datetime.utcnow().isoformat(),
            "source_timestamp": ts.isoformat(),
            "schema_version": "1.0",
        }

        # Add AVT data if available
        if ts in avt_slice.index:
            row = avt_slice.loc[ts]
            payload["avt_telemetry"] = {
                col: float(row[col]) for col in avt_slice.columns
                if pd.notna(row[col])
            }

        # Add 24-2000 data if available
        if ts in u24_slice.index:
            row = u24_slice.loc[ts]
            payload["unit_242000_telemetry"] = {
                col: float(row[col]) for col in u24_slice.columns
                if pd.notna(row[col])
            }

        # Publish to API, Redis, or print.
        if api_client and "unit_242000_telemetry" in payload:
            values = payload["unit_242000_telemetry"]
            if "Q21" not in values:
                logger.warning("Skipping %s: Q21 is absent", ts)
                continue
            q21_payload = {
                "timestamp": payload["source_timestamp"], "q21": values["Q21"],
                "operating_mode": "normal",
                "ingestion_mode": "replay",
                "values": {
                    **{key: value for key, value in values.items() if key != "Q21"},
                    **{key: value for key, value in payload.get("avt_telemetry", {}).items()
                       if key in {"F31", "T33", "T55"}},
                },
            }
            response = api_client.post("/q21/telemetry", json=q21_payload,
                                       headers={"X-Request-ID": f"replay-{ts.isoformat()}"})
            if response.status_code != 409:
                response.raise_for_status()
        elif redis_client:
            try:
                redis_client.xadd("telemetry.received", {"data": json.dumps(payload)})
            except Exception as e:
                logger.warning(f"Failed to publish: {e}")
        else:
            if i < 3:  # Print first 3 events in dry-run
                logger.info(f"[DRY-RUN] Event at {ts}: {len(payload.get('avt_telemetry', {}))} AVT + "
                           f"{len(payload.get('unit_242000_telemetry', {}))} 24-2000 signals")

        n_events += 1

        # Sleep to simulate realtime (adjusted by speed)
        if speed > 0 and i < len(timestamps) - 1:
            interval = (timestamps[i + 1] - ts).total_seconds() / speed
            time.sleep(min(interval, 1.0))  # Cap at 1 second for fast replay

        # Progress
        if (i + 1) % 100 == 0:
            logger.info(f"Replayed {i + 1}/{len(timestamps)} events ({(i+1)/len(timestamps)*100:.1f}%)")

    logger.info(f"Replay complete: {n_events} events published")


if __name__ == "__main__":
    main()
