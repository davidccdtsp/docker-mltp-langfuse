# Observabilidad: trace-generator → Grafana & Langfuse

Cómo fluyen métricas, trazas y logs desde el servicio `trace-generator` hasta Grafana, y cómo las trazas LLM llegan a Langfuse.

---

## Arquitectura general

```
trace-generator
    │
    ├─── Métricas (/metrics) ──► Alloy (scrape) ──────────────────► Mimir ──► Grafana
    │
    ├─── Trazas OTel (OTLP) ──► Alloy (4318) ──► Tempo ──────────────────► Grafana
    │                                 │
    │                                 └──► Loki (autologging raíz) ─────► Grafana
    │
    ├─── Logs (HTTP push) ────► Alloy (3100) ──► Loki ──────────────────► Grafana
    │
    └─── SDK Langfuse ────────► langfuse-web ──► ClickHouse ────────────► Grafana
                                             └──► PostgreSQL
```

---

## 1. Métricas

### 1.1 Métricas de aplicación (Prometheus)

`prometheus-fastapi-instrumentator` instrumenta automáticamente FastAPI y expone el endpoint `/metrics` en el puerto 8000. Contiene histogramas de latencia y contadores de peticiones HTTP por endpoint y código de estado.

**Pipeline**:

```
trace-generator:8000/metrics
    └──► prometheus.scrape "langfuse_stack" (Alloy, cada 15 s)
             └──► prometheus.remote_write "mimir"
                      └──► Mimir (remote write)
                               └──► Grafana (datasource Mimir)
```

Configuración relevante en `alloy/config.alloy`:

```alloy
prometheus.scrape "langfuse_stack" {
    targets        = [{"__address__" = "trace-generator:8000", service = "trace-generator"}]
    scrape_interval = "15s"
    forward_to     = [prometheus.remote_write.mimir.receiver]
    job_name       = "trace-generator"
}
```

Métricas clave generadas:

| Métrica | Descripción |
|---|---|
| `http_request_duration_seconds_*` | Histograma de latencia por endpoint |
| `http_requests_total` | Contador de peticiones por endpoint y status |

### 1.2 Métricas de trazas (spanmetrics)

Tempo genera automáticamente métricas RED a partir de los spans recibidos. No pasan por Alloy sino directamente desde Tempo a Mimir vía remote write.

Métricas generadas (prefijo `traces_spanmetrics_`):

| Métrica | Descripción |
|---|---|
| `traces_spanmetrics_calls_total` | Llamadas totales por span (label: `service`, `http_target`, `http_status_code`, `http_method`) |
| `traces_spanmetrics_latency_bucket/sum/count` | Histograma de latencia de spans |

Estas son las métricas que usan los dashboards **Trace Generator - MLT Dashboard** y **Trace Generator - Erroring Endpoints**.

> **Nota importante**: Tempo usa la label `service` (no `service_name`) en las spanmetrics. Las queries deben usar `service="trace-generator"`, no `service_name`.

### 1.3 Sondas HTTP (blackbox exporter)

Alloy comprueba la disponibilidad de `langfuse-web` y `trace-generator` mediante sondas HTTP cada 15 s.

```alloy
prometheus.exporter.blackbox "langfuse" {
    targets = [
        {name = "langfuse-web",    address = "http://langfuse-web:3000/api/public/health"},
        {name = "trace-generator", address = "http://trace-generator:8000/health"},
    ]
}
```

Métrica resultante: `probe_success{instance="trace-generator"}` — usada en el panel **Estado de servicios** del dashboard Langfuse.

---

## 2. Trazas

### 2.1 Inicialización del TracerProvider

`trace-generator/services/otel.py` configura el SDK de OpenTelemetry al importarse:

```python
_resource = Resource.create({"service.name": "trace-generator", "service.version": "1.0.0"})
_tracer_provider = TracerProvider(resource=_resource)
_tracer_provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint="http://alloy:4318/v1/traces"))
)
```

Todos los spans llevan `service.name="trace-generator"` como atributo de recurso.

### 2.2 Instrumentación automática

`api.py` instrumenta FastAPI y la librería `requests` al arrancar:

```python
FastAPIInstrumentor.instrument_app(app)   # spans HTTP server por cada request
RequestsInstrumentor().instrument()        # spans HTTP client por cada llamada saliente
```

Estos generan spans automáticos con atributos `http.method`, `http.target`, `http.status_code`.

### 2.3 Spans personalizados

| Span | Origen | Descripción |
|---|---|---|
| `simulate_agent_run` | `trace_service.py` | Span raíz de la traza sintética |
| `retrieval` | `trace_service.py` | Simula consulta a vector DB |
| `llm-call` | `trace_service.py` | Simula llamada al LLM |
| `post-processing` | `trace_service.py` | Post-procesado opcional (60% probabilidad) |
| `llm.complete` | `services/llm.py` | Llamada real al LLM en el endpoint `/complete` |

### 2.4 Pipeline de trazas en Alloy

```
trace-generator → OTLP HTTP (alloy:4318/v1/traces)
    └──► otelcol.receiver.otlp "otlp_receiver"
             ├──► otelcol.processor.batch "default" (1000 spans, timeout 2 s)
             │        └──► otelcol.exporter.otlp "tempo"
             │                  └──► Tempo (almacenamiento + búsqueda)
             │                           └──► Grafana (datasource Tempo)
             └──► otelcol.connector.spanlogs "autologging"
                      └──► otelcol.exporter.loki "autologging"
                               └──► loki.process "autologging"
                                        └──► loki.write "autologging"
                                                 └──► Loki {job="alloy"}
```

El conector `spanlogs.autologging` genera una línea de log por cada **span raíz** (cada traza completa). Incluye los atributos `http.method`, `http.target`, `http.status_code` y el campo `traceId` para correlación con Tempo en Grafana.

---

## 3. Logs

### 3.1 Logger estructurado

`trace-generator/services/loki_logger.py` implementa un `logging.Handler` que envía cada línea directamente a Loki vía HTTP:

```python
class _LokiHandler(logging.Handler):
    def emit(self, record):
        payload = {
            "streams": [{
                "stream": {"job": "trace-generator", "level": record.levelname.lower()},
                "values": [[str(int(record.created * 1e9)), self.format(record)]],
            }]
        }
        requests.post("http://alloy:3100/loki/api/v1/push", json=payload)
```

### 3.2 Pipeline de logs en Alloy

```
_LokiHandler → HTTP POST alloy:3100/loki/api/v1/push
    └──► loki.source.api "mythical" (escucha en :3100)
             └──► loki.process "mythical"
                      └──► loki.write "mythical"
                               └──► Loki
                                        └──► Grafana (datasource Loki)
```

### 3.3 Labels y queries

Los logs del generador tienen las siguientes labels en Loki:

| Label | Valores |
|---|---|
| `job` | `trace-generator` |
| `level` | `info`, `warning`, `error` |

Query Loki para ver todos los logs:
```logql
{job="trace-generator"} | logfmt
```

Query para solo errores:
```logql
{job="trace-generator", level="error"}
```

Los logs autogenerados por `spanlogs.autologging` usan `{job="alloy"}` y contienen el campo `service_name="trace-generator"`:
```logql
{job="alloy"} | logfmt | service_name="trace-generator"
```

---

## 4. Langfuse (trazas LLM)

### 4.1 Trazas sintéticas — `/generate`

`trace-generator/services/trace_service.py` usa el SDK de Langfuse para crear trazas con estructura multi-span:

```python
_lf = Langfuse(
    public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
    secret_key=os.environ["LANGFUSE_SECRET_KEY"],
    host=os.environ["LANGFUSE_HOST"],          # http://langfuse-web:3000
)

lf_trace = _lf.trace(name=f"{agent}-run", session_id=..., user_id=..., tags=[tenant, agent, model])
retrieval = lf_trace.span(name="retrieval", input={"query": prompt})
retrieval.end(output={"docs_retrieved": N})

generation = lf_trace.generation(name="llm-call", model=model, input=[...], usage={...})
generation.end(output={"role": "assistant", "content": "..."})

post = lf_trace.span(name="post-processing", ...)
post.end(...)

_lf.score(trace_id=lf_trace.id, name="quality", value=0.85)
lf_trace.update(output={"status": "completed"})
_lf.flush()  # envío inmediato
```

Estructura de la traza en Langfuse:

```
{agent}-run  (trace)
├── retrieval        (span)
├── llm-call         (generation) ← contiene tokens, modelo, latencia
└── post-processing  (span, 60% probabilidad)
```

### 4.2 Trazas reales — `/complete`

`trace-generator/services/llm.py` realiza una llamada real al LLM (Google Gemini) e instrumenta tanto Langfuse como OTel:

```python
# Langfuse
lf_trace = _lf.trace(name=f"complete/{provider}", tags=[provider, model])
generation = lf_trace.generation(name="llm-call", model=model, input=[{"role": "user", ...}])
# ... llamada real al LLM ...
generation.end(output=response_text, usage={"promptTokens": N, "completionTokens": M, ...})
lf_trace.update(output=response_text)
_lf.flush()

# OTel (paralelo)
with tracer.start_as_current_span("llm.complete") as span:
    span.set_attribute("llm.provider", provider)
    span.set_attribute("llm.prompt_tokens", N)
    span.set_attribute("llm.completion_tokens", M)
```

### 4.3 Pipeline hasta ClickHouse

```
Langfuse SDK (_lf.flush())
    └──► HTTP POST langfuse-web:3000  (API pública de Langfuse)
             ├──► PostgreSQL  (metadatos: proyectos, usuarios, sesiones, scores)
             └──► ClickHouse  (eventos, observaciones, generaciones con tokens y latencias)
                      └──► Grafana (datasource ClickHouse — "ClickHouse (Langfuse)")
```

### 4.4 Tablas ClickHouse relevantes

| Tabla | Contenido |
|---|---|
| `langfuse.traces` | Una fila por traza: `id`, `name`, `user_id`, `session_id`, `timestamp`, `tags`, `metadata` |
| `langfuse.observations` | Spans y generaciones anidadas dentro de cada traza |

Query de ejemplo para explorar trazas:
```sql
SELECT id, name, user_id, timestamp
FROM langfuse.traces
ORDER BY timestamp DESC
LIMIT 20
```

Query para tokens por modelo:
```sql
SELECT
    model,
    sum(prompt_tokens)     AS total_prompt_tokens,
    sum(completion_tokens) AS total_completion_tokens
FROM langfuse.observations
WHERE type = 'GENERATION'
  AND start_time >= now() - INTERVAL 24 HOUR
GROUP BY model
ORDER BY total_completion_tokens DESC
```

---

## 5. Resumen de señales por destino

| Señal | Origen | Destino | Grafana datasource |
|---|---|---|---|
| Métricas HTTP app | `/metrics` (Prometheus) | Mimir | Mimir |
| Métricas spanmetrics | Tempo (desde spans OTel) | Mimir | Mimir |
| Métricas blackbox | Alloy blackbox exporter | Mimir | Mimir |
| Trazas OTel | SDK OTel → Alloy → Tempo | Tempo | Tempo |
| Logs app | `_LokiHandler` → Alloy → Loki | Loki | Loki |
| Logs autologging | Alloy spanlogs → Loki | Loki | Loki |
| Trazas LLM sintéticas | SDK Langfuse → langfuse-web | ClickHouse | ClickHouse (Langfuse) |
| Trazas LLM reales | SDK Langfuse → langfuse-web | ClickHouse | ClickHouse (Langfuse) |

---

## 6. Dashboards relacionados

| Dashboard | Señales usadas |
|---|---|
| **Trace Generator - MLT Dashboard** | Mimir (spanmetrics), Loki |
| **Trace Generator - Erroring Endpoints** | Mimir (spanmetrics), Tempo (TraceQL) |
| **Trace Generator - Traces** | Mimir (spanmetrics), Loki, Tempo |
| **Langfuse — Observabilidad PoC** | Mimir (probe + Prometheus), ClickHouse, Loki |
