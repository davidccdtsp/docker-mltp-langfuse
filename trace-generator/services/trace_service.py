import os
import random
import time
import uuid

from langfuse import Langfuse
from opentelemetry import trace as otel_trace

from models.traces import AGENTS, MODELS, TENANTS, USERS
from services.otel import tracer

_lf = Langfuse(
    public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
    secret_key=os.environ["LANGFUSE_SECRET_KEY"],
    host=os.environ["LANGFUSE_HOST"],
)


def simulate_agent_run(
    tenant: str,
    agent: str,
    model: str,
    user_id: str,
    prompt: str | None = None,
) -> str:
    """Generates a synthetic LLM trace in Langfuse. Returns the trace_id."""
    with tracer.start_as_current_span("simulate_agent_run") as span:
        span.set_attribute("tenant", tenant)
        span.set_attribute("agent", agent)
        span.set_attribute("model", model)
        span.set_attribute("user_id", user_id)

        session_id = str(uuid.uuid4())
        user_prompt = prompt or f"[{tenant}] task input for {agent}"

        lf_trace = _lf.trace(
            name=f"{agent}-run",
            session_id=session_id,
            user_id=user_id,
            metadata={"tenant_id": tenant, "agent_type": agent, "environment": "poc"},
            tags=[tenant, agent, model],
        )

        with tracer.start_as_current_span("retrieval") as r_span:
            r_span.set_attribute("query", user_prompt)
            retrieval = lf_trace.span(name="retrieval", input={"query": user_prompt})
            time.sleep(random.uniform(0.05, 0.25))
            docs = random.randint(3, 12)
            retrieval.end(output={"docs_retrieved": docs}, metadata={"source": "vector-db"})
            r_span.set_attribute("docs_retrieved", docs)

        prompt_tokens = random.randint(400, 4000)
        completion_tokens = random.randint(80, 900)
        latency_ms = random.randint(600, 4000)

        with tracer.start_as_current_span("llm-call") as llm_span:
            llm_span.set_attribute("model", model)
            llm_span.set_attribute("prompt_tokens", prompt_tokens)
            llm_span.set_attribute("completion_tokens", completion_tokens)
            llm_span.set_attribute("latency_ms", latency_ms)
            generation = lf_trace.generation(
                name="llm-call",
                model=model,
                model_parameters={"temperature": 0.7, "max_tokens": 1024},
                input=[
                    {"role": "system", "content": f"You are a {agent} assistant."},
                    {"role": "user", "content": user_prompt},
                ],
                usage={
                    "promptTokens": prompt_tokens,
                    "completionTokens": completion_tokens,
                    "totalTokens": prompt_tokens + completion_tokens,
                },
                metadata={"tenant_id": tenant},
            )
            time.sleep(latency_ms / 1000)
            generation.end(
                output={"role": "assistant", "content": "Task completed successfully."},
                metadata={"latency_ms": latency_ms},
            )

        if random.random() > 0.4:
            with tracer.start_as_current_span("post-processing"):
                post = lf_trace.span(name="post-processing", input={"action": "format-output"})
                time.sleep(random.uniform(0.02, 0.1))
                post.end(output={"status": "formatted"})

        if random.random() > 0.5:
            _lf.score(
                trace_id=lf_trace.id,
                name="quality",
                value=round(random.uniform(0.5, 1.0), 2),
                comment="auto-scored by poc-generator",
            )

        lf_trace.update(output={"status": "completed"}, metadata={"tenant_id": tenant})
        span.set_attribute("langfuse.trace_id", lf_trace.id)
        return lf_trace.id


def flush() -> None:
    _lf.flush()
