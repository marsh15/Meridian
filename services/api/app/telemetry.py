"""OpenTelemetry wiring (phase 5): traces + metrics to an OTLP collector.

Enabled iff settings.otlp_endpoint is set ("" in tests and plain dev runs —
the no-op API makes every metrics call free). The collector in compose
forwards metrics to Prometheus (scrapeable on :8889) and traces to Tempo;
see docker/otel-collector.yaml and the order-pipeline Grafana dashboard.

set_global_providers is called at most once per process — relay, consumers
and the API each boot their own process with their own service name.
"""

import logging
from typing import Any

from fastapi import FastAPI

from app.config import settings

log = logging.getLogger("meridian.telemetry")

_providers: dict[str, Any] = {}


def setup_telemetry(
    app: FastAPI | None = None, service_name: str = "meridian-api"
) -> None:
    if not settings.otlp_endpoint:
        return
    if _providers.get("set"):
        # a second setup in the same process (tests) keeps the first
        return

    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    endpoint = settings.otlp_endpoint.rstrip("/")
    resource = Resource.create({"service.name": service_name})

    # short exporter timeout: a wedged collector must never accumulate
    # stuck export threads — batches drop and the app keeps serving
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces", timeout=2),
            export_timeout_millis=2_000,
        )
    )

    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[
            PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics", timeout=2),
                export_interval_millis=5_000,
                export_timeout_millis=2_000,
            )
        ],
    )

    from opentelemetry import metrics, trace

    trace.set_tracer_provider(tracer_provider)
    metrics.set_meter_provider(meter_provider)
    _providers["set"] = True

    if app is not None:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(
            app, tracer_provider=tracer_provider, excluded_urls="api/health"
        )

    log.info("telemetry on: %s → %s", service_name, endpoint)
