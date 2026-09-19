# 🔐 УЧЕТНЫЕ ЗАПИСИ И ДОСТУП

## 🌐 Operator Console (http://localhost:8000)

### **БЕЗ АВТОРИЗАЦИИ** ✅

API работает **БЕЗ авторизации** по умолчанию.

Все endpoints доступны напрямую:
- ✅ GET /health
- ✅ GET /snapshot
- ✅ GET /q21/status
- ✅ GET /timeline/events
- ✅ POST /q21/telemetry
- ✅ WebSocket /ws/q21/live

**Просто откройте:** http://localhost:8000

---

## 📊 Grafana (http://localhost:3000)

### Учетные данные по умолчанию:

```
Логин:    admin
Пароль:   admin
```

**При первом входе:**
1. Откройте http://localhost:3000
2. Введите `admin` / `admin`
3. Grafana предложит сменить пароль
4. Можете пропустить (Skip) или установить новый

**Dashboard:**
- Нажмите "Dashboards" → "Browse"
- Выберите "Q21 Shadow Pipeline" или "Neftekod Q21 Production"

---

## 📈 Prometheus (http://localhost:9090)

### **БЕЗ АВТОРИЗАЦИИ** ✅

Prometheus доступен без логина.

**Просто откройте:** http://localhost:9090

**Проверить метрики:**
1. Перейти в Graph
2. Ввести: `neftekod_q21_current_ppm`
3. Нажать "Execute"

---

## 🔧 Безопасность (для production)

### Текущая конфигурация — DEMO MODE

Для демонстрации жюри авторизация **отключена**.

### Для production нужно включить:

**В `src/api/security.py`:**
```python
# Раскомментировать проверку токенов:
def operator_access(request: Request) -> Identity:
    # Проверить API token
    # Проверить JWT token
    # Вернуть Identity
```

**Добавить в docker-compose.yml:**
```yaml
environment:
  - API_SECRET_KEY=your-secret-key
  - GRAFANA_ADMIN_PASSWORD=secure-password
```

---

## 🎯 ДЛЯ ДЕМОНСТРАЦИИ ЖЮРИ

### Быстрый доступ:

| Сервис | URL | Логин | Пароль |
|--------|-----|-------|--------|
| Operator Console | http://localhost:8000 | - | - |
| Grafana | http://localhost:3000 | admin | admin |
| Prometheus | http://localhost:9090 | - | - |

**Всё готово к показу без настройки! ✅**

---

## 💡 Если Grafana просит пароль

### Вариант 1: Стандартные credentials
```
admin / admin
```

### Вариант 2: Сбросить пароль
```bash
docker compose exec grafana grafana-cli admin reset-admin-password newpassword
```

### Вариант 3: Проверить логи
```bash
docker compose logs grafana | grep -i password
```

---

## ✅ ИТОГО

**Operator Console:** Нет авторизации, открывается сразу  
**Grafana:** admin/admin (стандартные credentials)  
**Prometheus:** Нет авторизации

**Всё готово для демонстрации! 🚀**
