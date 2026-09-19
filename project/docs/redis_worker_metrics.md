# Redis Worker метрики для Q21 Stream Worker

Добавить в `scripts/q21_stream_worker.py`:

```python
from prometheus_client import Counter, Gauge, Histogram, start_http_server

# Метрики Redis Worker
REDIS_STREAM_LAG = Gauge('neftekod_redis_stream_lag_messages', 'Messages pending in stream')
REDIS_PROCESSED = Counter('neftekod_redis_processed_total', 'Messages processed from stream')
REDIS_DLQ = Counter('neftekod_redis_dlq_total', 'Messages moved to DLQ')
REDIS_PROCESSING_TIME = Histogram('neftekod_redis_processing_seconds', 'Message processing time')

# Запустить Prometheus exporter на отдельном порту
start_http_server(9101)

# В основном цикле обработки
while True:
    with REDIS_PROCESSING_TIME.time():
        # Обработка сообщения
        ...
    REDIS_PROCESSED.inc()
    
    # Обновить lag
    pending_info = redis_client.xpending(stream_name, group_name)
    REDIS_STREAM_LAG.set(pending_info['pending'])
```

Добавить scrape config в `monitoring/prometheus/prometheus.yml`:

```yaml
scrape_configs:
  - job_name: neftekod-redis-worker
    static_configs:
      - targets: ["q21-stream-worker:9101"]
        labels:
          application: neftekod
          component: redis-worker
```

Панели для Grafana Q21 Dashboard:
- Redis stream lag (pending messages)
- Processing rate (msg/s)
- DLQ count
- Processing time p95
