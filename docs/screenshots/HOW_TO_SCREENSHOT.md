# Скриншоты для README

К сожалению, я не могу сделать реальные скриншоты через браузер, так как у меня нет доступа к графическому интерфейсу.

## Но я могу помочь вам их создать!

### Шаг 1: Запустите систему
```bash
cd /Users/falexsun/code/Нефтекод/project
./scripts/start_demo.sh
```

### Шаг 2: Сделайте скриншоты (Cmd+Shift+4 на Mac)

#### 1. Operator Console
- Откройте: http://localhost:8000
- Дождитесь загрузки интерфейса
- Скриншот всего окна
- Сохраните как: `operator-console.png`

#### 2. Grafana Dashboard
- Откройте: http://localhost:3000
- Логин: admin, Пароль: neftekod-local
- Перейдите: Dashboards → Q21 Shadow Pipeline
- Скриншот dashboard с графиками
- Сохраните как: `grafana-dashboard.png`

#### 3. Timeline Events (после demo)
- Запустите: `uv run python scripts/demo_replay.py --scenario exceedance --speed 100`
- Откройте: http://localhost:8000
- Прокрутите до Timeline Events
- Скриншот ленты событий
- Сохраните как: `timeline-events.png`

#### 4. Demo Replay (терминал)
- Во время выполнения demo_replay.py
- Скриншот терминала с прогрессом
- Сохраните как: `demo-replay.png`

#### 5. Prometheus Metrics
- Откройте: http://localhost:9090
- В поле введите: `neftekod_q21_current_ppm`
- Нажмите Execute
- Скриншот графика
- Сохраните как: `prometheus-metrics.png`

#### 6. API Documentation
- Откройте: http://localhost:8000/docs
- Прокрутите до видимости endpoints
- Скриншот Swagger UI
- Сохраните как: `api-docs.png`

### Шаг 3: Поместите скриншоты сюда
Все файлы должны быть в этой папке.

### Шаг 4: Загрузите на GitHub
```bash
cd /Users/falexsun/code/Нефтекод
git add docs/screenshots/*.png
git commit -m "📸 Добавлены скриншоты работающей системы"
git push
```

## Альтернатива: Использовать placeholder изображения

Пока нет реальных скриншотов, можно использовать placeholder:
```markdown
![Operator Console](https://via.placeholder.com/800x400/1a1a1a/00ff00?text=Operator+Console)
```

Но лучше сделать настоящие скриншоты для жюри!
