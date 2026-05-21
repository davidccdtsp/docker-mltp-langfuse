import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_OTLP_ENDPOINT = os.environ.get("OTLP_ENDPOINT", "http://alloy:4318")

_resource = Resource.create({"service.name": "trace-generator", "service.version": "1.0.0"})

_tracer_provider = TracerProvider(resource=_resource)
_tracer_provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{_OTLP_ENDPOINT}/v1/traces"))
)
trace.set_tracer_provider(_tracer_provider)

tracer = trace.get_tracer("trace-generator")
