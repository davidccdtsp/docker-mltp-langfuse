# mltp-langfuse

Sandbox de observabilidad con un stack unificado: MLTP (Métricas · Logs · Trazas · Perfiles) + Langfuse (LLM observability) + app de demo, todo arrancado con un único `docker compose up -d`.

Este repositorio ha sido generado tomando como base [Grafana - intro-to-mltp](https://github.com/grafana/intro-to-mltp) al que se han realizado las siguentes modificaciones:

* Eliminar backend existente y dashboards asociados.
* Añadir backend propio y generar dashboards en base a los nuevos datos.
* Añandir conexión al data source **clickhouse**

---

## Prerequisitos

- Docker con Compose integrado (`docker compose`)
- Puertos libres (ver tabla al final)
- Fichero `.env` en la raíz (incluido en el repo con valores por defecto)

---

## Arranque

```bash
docker compose up -d
```

Langfuse tarda ~60-90 s: espera a que `postgres`, `clickhouse` y `redis` pasen sus healthchecks antes de iniciar `langfuse-web` y `langfuse-worker`. La app mythical espera a que `mythical-queue` (RabbitMQ) pase el suyo.

```bash
docker compose ps          # ver estado de todos los servicios
docker compose logs -f     # seguir logs en tiempo real
```

## Parar

```bash
docker compose down        # para y elimina contenedores (datos de volúmenes persisten)
docker compose down -v     # reset completo, elimina también los volúmenes
```

---

## Servicios y URLs

| Servicio | URL | Descripción |
|---|---|---|
| **Grafana** | http://localhost:3000 | UI principal (acceso Admin anónimo, sin login) |
| **Frontend** | http://localhost:3001 | App React "Mythical Beasts" — genera telemetría Faro |
| **Langfuse** | http://localhost:3002 | UI LLM observability |
| **Trace Generator API** | http://localhost:8000 | API REST del generador de trazas |
| **Swagger UI** | http://localhost:8000/docs | Documentación interactiva |
| **Alloy** | http://localhost:12347 | Grafo de componentes del collector |
| **RabbitMQ** | http://localhost:15672 | UI de la cola (`guest` / `guest`) |
| MinIO Console | http://localhost:9001 | Gestión del bucket S3 local |
| Mimir API | http://localhost:9009 | Remote write de métricas |
| Loki API | http://localhost:3100 | Push de logs |
| Tempo API | http://localhost:3200 | Query de trazas |
| Pyroscope API | http://localhost:4040 | Query de perfiles |

---

## Arquitectura

```
trace-generator
  ├── /metrics (Prometheus) ──► Alloy (scrape) ──► Mimir ──► Grafana
  ├── trazas OTel ──────────► Alloy (4318) ──► Tempo ─────► Grafana
  │                              └─► Loki (autologging raíz)
  ├── logs HTTP ────────────► Alloy (3100) ──► Loki ──────► Grafana
  └── SDK Langfuse ─────────► langfuse-web ──► ClickHouse ─► Grafana
                                             └─► PostgreSQL

k6 ──► trace-generator ──► Mimir (métricas k6) ──► Grafana

Tempo ──► Mimir (spanmetrics traces_spanmetrics_*)
Alloy ──► Mimir (blackbox probe UP/DOWN)
```

> Ver [OBSERVABILITY.md](OBSERVABILITY.md) para la descripción detallada de cada pipeline.

---

## Stack MLTP — pruebas mínimas

Basado en el [intro-to-mltp](https://github.com/grafana/intro-to-mltp) de Grafana Labs.

**1. Métricas (Mimir)**
- Grafana → Explore → datasource `Mimir`
- Query: `histogram_quantile(0.95, sum(rate(mythical_request_times_bucket[15s])) by (le, beast))`

**2. Logs (Loki)**
- Grafana → Explore → datasource `Loki`
- Query: `{job="mythical-beasts-requester"} | logfmt`

**3. Trazas (Tempo)**
- Grafana → Explore → datasource `Tempo`
- TraceQL: `{ .service.name = "mythical-server" && duration > 100ms }`

**4. Perfiles (Pyroscope)**
- Grafana → Apps → Grafana Pyroscope
- Service: `mythical-server`, métrica: `process_cpu:cpu:nanoseconds:cpu:nanoseconds`

**5. Dashboard MLT**
- Grafana → Dashboards → **MLT Dashboard**

**6. k6 load test**
- Grafana → Dashboards → **Official k6 Test Result**

---

## Stack Langfuse

### Acceso a Langfuse

| Campo | Valor |
|---|---|
| URL | http://localhost:3002 |
| Email | `admin@poc.local` |
| Password | `admin123` |
| Organización | `company-poc` |
| Proyecto | `poc` |

### Generador de trazas — API HTTP

Swagger UI interactivo: **http://localhost:8000/docs** . Simula una llamada a un agente generando multiples trazas correspondientes a las diversas llamadas que el agente pueda realizar a diversos modelos.

**Enviar una traza:**

```bash
curl -s -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Analyze the quarterly revenue report for EMEA region."}' | jq
```

**Respuesta:**

```json
{
  "trace_id": "abc123...",
  "session_id": "abc123...",
  "tenant": "acme-corp",
  "agent": "document-analyzer",
  "model": "gpt-4o",
  "user_id": "user-acme-corp-3",
  "prompt": "Analyze the quarterly revenue report for EMEA region."
}
```

Parámetros opcionales del body (todos aleatorios si se omiten):

| Campo | Tipo | Descripción |
|---|---|---|
| `prompt` | string | **Obligatorio.** Texto del prompt del usuario. |
| `tenant` | string | Tenant: `acme-corp`, `globex`, `initech`, `umbrella`, `hooli` |
| `agent` | string | Agente: `document-analyzer`, `email-responder`, `data-extractor`, `report-generator` |
| `model` | string | Modelo LLM: `gpt-4o`, `gpt-4o-mini`, `claude-sonnet-4-6`, `claude-haiku-4-5` |

### Variables de entorno (`.env`)

El fichero `.env` contiene credenciales para desarrollo local. **No usar en producción.**

| Variable | Descripción |
|---|---|
| `POSTGRES_USER` / `POSTGRES_PASSWORD` | Credenciales PostgreSQL (Langfuse) |
| `CLICKHOUSE_PASSWORD` | Contraseña ClickHouse |
| `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` | Credenciales MinIO |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | Claves del proyecto `poc` (organización `company-poc`) |
| `LANGFUSE_NEXTAUTH_SECRET` / `LANGFUSE_SALT` / `LANGFUSE_ENCRYPTION_KEY` | Secretos de la app |

---

## Integración Grafana ↔ Langfuse

### Dashboard "Langfuse — Observabilidad PoC"

Grafana → Dashboards → **Langfuse — Observabilidad PoC**

| Panel | Fuente | Qué muestra |
|---|---|---|
| Estado de servicios | Mimir (probe HTTP) | UP/DOWN de `langfuse-web` y `trace-generator` |
| Requests/s API | Mimir (Prometheus) | Tasa de peticiones por endpoint |
| Latencia p95 | Mimir (Prometheus) | Percentil 95 de latencia por endpoint |
| Trazas LLM | ClickHouse | Conteo de trazas por intervalo de 5 min |
| Top modelos | ClickHouse | Modelos LLM más utilizados (últimas 24h) |
| Top tenants | ClickHouse | Tenants con más actividad (últimas 24h) |
| Logs | Loki | Log lines del generador en tiempo real |

### Datasource ClickHouse

Grafana → Explore → datasource **ClickHouse (Langfuse)**

```sql
SELECT id, name, user_id, timestamp
FROM langfuse.traces
ORDER BY timestamp DESC
LIMIT 20
```

### Completions LLM reales — `/complete`

Envía un prompt a un modelo LLM real y almacena la traza en Langfuse (ClickHouse).

```bash
curl -s -X POST http://localhost:8000/complete \
  -H "Content-Type: application/json" \
  -d '{
    "api_key": "TU_GOOGLE_API_KEY",
    "provider": "google",
    "model": "gemini-2.0-flash",
    "prompt": "¿Qué es RAG en dos frases?"
  }' | jq
```

**Respuesta:**

```json
{
  "provider": "google",
  "model": "gemini-2.0-flash",
  "response": "RAG (Retrieval-Augmented Generation) es...",
  "prompt_tokens": 12,
  "completion_tokens": 48
}
```

| Campo | Tipo | Requerido | Descripción |
|---|---|---|---|
| `api_key` | string | ✓ | Clave de API del proveedor |
| `provider` | string | — | Proveedor LLM. Actualmente: `google` (default) |
| `model` | string | — | Modelo a usar. Default: `gemini-2.0-flash` |
| `prompt` | string | ✓ | Texto a enviar al modelo |

Cada llamada genera:
- Una **traza Langfuse** (`complete/google`) con la generación real (tokens, latencia, input/output) visible en http://localhost:3002 y en el dashboard de Grafana.
- Un **OTel span** `llm.complete` con atributos `llm.provider`, `llm.model`, `llm.prompt_tokens`, `llm.completion_tokens`, visible en Grafana Tempo.

### Endpoint de logs del generador

```bash
curl -s -X POST http://localhost:8000/logs \
  -H "Content-Type: application/json" \
  -d '{"count": 10, "level": "warning"}' | jq
```

| Campo | Tipo | Descripción |
|---|---|---|
| `count` | int (1-50) | Número de log lines a generar. Defecto: 5. |
| `level` | string | Nivel del log: `info`, `warning`, `error`. Aleatorio si se omite. |

---

## Mapa de puertos

| Puerto | Servicio |
|---|---|
| 3000 | Grafana |
| 3001 | mythical-frontend |
| 3002 | Langfuse web |
| 3100 | Loki API |
| 3200 | Tempo API |
| 4000 | mythical-server |
| 4001 | mythical-requester |
| 4002 | mythical-recorder |
| 4040 | Pyroscope API |
| 4317 | Alloy OTLP gRPC |
| 4318 | Alloy OTLP HTTP |
| 5432 | PostgreSQL (mythical) |
| 5672 | RabbitMQ AMQP |
| 8000 | Trace Generator API + Swagger |
| 9001 | MinIO Console |
| 9009 | Mimir API |
| 12347 | Alloy UI |
| 12350 | Alloy Faro receiver |
| 15672 | RabbitMQ UI |
