from pydantic import BaseModel, Field

TENANTS = ["acme-corp", "globex", "initech", "umbrella", "hooli"]
MODELS = ["gpt-4o", "gpt-4o-mini", "claude-sonnet-4-6", "claude-haiku-4-5"]
AGENTS = ["document-analyzer", "email-responder", "data-extractor", "report-generator"]
USERS = {t: [f"user-{t}-{i}" for i in range(1, 6)] for t in TENANTS}


class GenerateRequest(BaseModel):
    prompt: str = Field(
        ...,
        description="Prompt que se usará como mensaje de usuario en la traza generada.",
        examples=["Analyze the quarterly revenue report for EMEA region."],
    )
    tenant: str | None = Field(
        default=None,
        description=f"Tenant al que asociar la traza. Aleatorio si se omite. Opciones: {TENANTS}",
        examples=["acme-corp"],
    )
    agent: str | None = Field(
        default=None,
        description=f"Tipo de agente simulado. Aleatorio si se omite. Opciones: {AGENTS}",
        examples=["document-analyzer"],
    )
    # model: str | None = Field(
    #     default=None,
    #     description=f"Modelo LLM simulado. Aleatorio si se omite. Opciones: {MODELS}",
    #     examples=["gpt-4o"],
    # )


class GenerateResponse(BaseModel):
    trace_id: str
    session_id: str = Field(description="UUID de la sesión generada.")
    tenant: str
    agent: str
    model: str
    user_id: str
    prompt: str


class LogRequest(BaseModel):
    count: int = Field(
        default=5, ge=1, le=50,
        description="Número de log lines a generar.",
    )
    level: str | None = Field(
        default=None,
        description="Nivel del log (info/warning/error). Aleatorio si se omite.",
        examples=["warning"],
    )


class CompletionRequest(BaseModel):
    api_key: str = Field(
        ...,
        description="API key del proveedor LLM.",
    )
    provider: str = Field(
        default="google",
        description="Proveedor LLM. Soportados: google",
        examples=["google"],
    )
    model: str = Field(
        default="gemini-2.0-flash",
        description="Nombre del modelo a usar.",
        examples=["gemini-2.0-flash", "gemini-1.5-flash"],
    )
    prompt: str = Field(
        ...,
        description="Texto del prompt a enviar al modelo.",
        examples=["Explica qué es una base de datos vectorial en dos frases."],
    )


class CompletionResponse(BaseModel):
    provider: str
    model: str
    response: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
