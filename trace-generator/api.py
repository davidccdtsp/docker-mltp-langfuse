"""
Trace Generator API — puerto HTTP (FastAPI).
Swagger UI disponible en /docs.
"""
import random
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Body, FastAPI, HTTPException
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from prometheus_fastapi_instrumentator import Instrumentator

from models.traces import AGENTS, MODELS, TENANTS, USERS, CompletionRequest, CompletionResponse, GenerateRequest, GenerateResponse, LogRequest
from services.loki_logger import logger
from services.llm import call_llm
from services.llm import flush as flush_llm
from services.otel import tracer  # noqa: F401 — initializes TracerProvider as side-effect
from services.trace_service import flush, simulate_agent_run

RequestsInstrumentor().instrument()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("event=startup status=ok")
    yield
    logger.info("event=shutdown status=ok")


app = FastAPI(
    title="Trace Generator API",
    description="Genera trazas sintéticas en Langfuse a partir de un prompt.",
    version="1.0.0",
    lifespan=lifespan,
)

FastAPIInstrumentor.instrument_app(app)
Instrumentator().instrument(app).expose(app)


@app.get("/health", tags=["status"])
def health() -> dict:
    return {"status": "ok"}


@app.get("/probe/error", tags=["probe"])
def probe_error() -> None:
    """Dispara un log de error y devuelve HTTP 500 para testear alertas de monitorización."""
    logger.error("event=probe_error status=triggered")
    raise HTTPException(status_code=500, detail="Probe error triggered for monitoring")


@app.post("/generate", response_model=GenerateResponse, tags=["traces"])
def generate(body: Annotated[GenerateRequest, Body()]) -> GenerateResponse:
    """
    Genera una única traza en Langfuse con el prompt proporcionado.

    - **prompt**: texto que se inyecta como mensaje de usuario en la llamada al LLM simulado.
    - El resto de campos son opcionales; si se omiten se eligen aleatoriamente.
    """
    tenant = body.tenant or random.choice(TENANTS)
    agent = body.agent or random.choice(AGENTS)
    model = body.model or random.choice(MODELS)
    user_id = random.choice(USERS[tenant])

    logger.info(f"event=generate_start tenant={tenant} agent={agent} model={model}")

    trace_id = simulate_agent_run(
        tenant=tenant,
        agent=agent,
        model=model,
        user_id=user_id,
        prompt=body.prompt,
    )
    flush()

    logger.info(f"event=generate_ok tenant={tenant} agent={agent} model={model} trace_id={trace_id}")

    return GenerateResponse(
        trace_id=trace_id,
        session_id=trace_id,
        tenant=tenant,
        agent=agent,
        model=model,
        user_id=user_id,
        prompt=body.prompt,
    )


@app.post("/complete", response_model=CompletionResponse, tags=["llm"])
def complete(body: Annotated[CompletionRequest, Body()]) -> CompletionResponse:
    """
    Envía un prompt a un modelo LLM real y devuelve la respuesta.

    - **api_key**: clave de API del proveedor.
    - **provider**: proveedor LLM (`google`).
    - **model**: nombre del modelo (p. ej. `gemini-2.0-flash`).
    - **prompt**: texto a enviar.
    """
    logger.info(f"event=complete_start provider={body.provider} model={body.model}")
    try:
        result = call_llm(
            provider=body.provider,
            api_key=body.api_key,
            model=body.model,
            prompt=body.prompt,
        )
    except ValueError as exc:
        logger.error(f"event=complete_error detail={exc}")
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error(f"event=complete_error detail={exc}")
        raise HTTPException(status_code=502, detail=f"Error del proveedor: {exc}")

    flush_llm()
    logger.info(
        f"event=complete_ok provider={body.provider} model={body.model} "
        f"prompt_tokens={result.get('prompt_tokens')} completion_tokens={result.get('completion_tokens')}"
    )
    return CompletionResponse(
        provider=body.provider,
        model=body.model,
        response=result["text"],
        prompt_tokens=result.get("prompt_tokens"),
        completion_tokens=result.get("completion_tokens"),
    )


@app.post("/logs", tags=["logs"])
def generate_logs(body: Annotated[LogRequest, Body()] = LogRequest()) -> dict:
    """
    Genera N log lines estructurados y los envía a Loki vía Alloy.

    Útil para probar el pipeline de logs: trace-generator → Alloy → Loki → Grafana.

    - **count**: número de líneas a generar (1-50, defecto 5).
    - **level**: nivel del log (info/warning/error). Aleatorio si se omite.
    """
    _dispatch = {"info": logger.info, "warning": logger.warning, "error": logger.error}
    valid_levels = [body.level] if body.level in _dispatch else list(_dispatch)

    logger.info(f"event=log_generation_start count={body.count} level={body.level or 'random'}")

    entries = []
    for _ in range(body.count):
        tenant = random.choice(TENANTS)
        agent = random.choice(AGENTS)
        lvl = random.choice(valid_levels)
        _dispatch[lvl](f"event=synthetic_log tenant={tenant} agent={agent}")
        entries.append({"level": lvl, "tenant": tenant, "agent": agent})

    logger.info(f"event=log_generation_ok count={body.count}")
    return {"generated": body.count, "entries": entries}
