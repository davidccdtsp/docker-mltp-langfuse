import os
import time

from langfuse import Langfuse

from services.otel import tracer

_lf = Langfuse(
    public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
    secret_key=os.environ["LANGFUSE_SECRET_KEY"],
    host=os.environ["LANGFUSE_HOST"],
)

_SUPPORTED_PROVIDERS = ["google"]


def _call_google(api_key: str, model: str, prompt: str) -> dict:
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    client = genai.GenerativeModel(model)
    response = client.generate_content(prompt)
    usage = response.usage_metadata
    return {
        "text": response.text,
        "prompt_tokens": getattr(usage, "prompt_token_count", None),
        "completion_tokens": getattr(usage, "candidates_token_count", None),
    }


def call_llm(provider: str, api_key: str, model: str, prompt: str) -> dict:
    """Calls a real LLM. Records an OTel span and a Langfuse generation."""
    handlers = {"google": _call_google}
    key = provider.lower()
    if key not in handlers:
        raise ValueError(f"Proveedor '{provider}' no soportado. Disponibles: {_SUPPORTED_PROVIDERS}")

    lf_trace = _lf.trace(
        name=f"complete/{provider}",
        metadata={"provider": provider},
        tags=[provider, model],
    )
    generation = lf_trace.generation(
        name="llm-call",
        model=model,
        input=[{"role": "user", "content": prompt}],
    )

    with tracer.start_as_current_span("llm.complete") as span:
        span.set_attribute("llm.provider", provider)
        span.set_attribute("llm.model", model)
        span.set_attribute("llm.prompt_chars", len(prompt))

        t0 = time.monotonic()
        result = handlers[key](api_key, model, prompt)
        latency_ms = int((time.monotonic() - t0) * 1000)

        prompt_tokens = result.get("prompt_tokens")
        completion_tokens = result.get("completion_tokens")
        total_tokens = (prompt_tokens or 0) + (completion_tokens or 0)

        generation.end(
            output=result["text"],
            usage={
                "promptTokens": prompt_tokens,
                "completionTokens": completion_tokens,
                "totalTokens": total_tokens,
            },
            metadata={"latency_ms": latency_ms},
        )
        lf_trace.update(output=result["text"])

        span.set_attribute("llm.latency_ms", latency_ms)
        if prompt_tokens is not None:
            span.set_attribute("llm.prompt_tokens", prompt_tokens)
        if completion_tokens is not None:
            span.set_attribute("llm.completion_tokens", completion_tokens)

        return result


def flush() -> None:
    _lf.flush()
