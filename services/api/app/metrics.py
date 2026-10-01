"""App instruments (phase 5).

Instruments are created unconditionally from the global meter: without a
MeterProvider the OpenTelemetry API hands back no-ops, so call sites never
branch on telemetry being enabled. Dotted names + unit attributes are
translated by the collector to Prometheus conventions
(meridian.order.latency + unit s → meridian_order_latency_seconds).
"""

from opentelemetry import metrics
from opentelemetry.metrics import Observation

meter = metrics.get_meter("meridian")

# latency histograms recorded in seconds; the OTel default boundaries are
# millisecond-scale and would lump every order into one bucket. Passed as
# advisory — the SDK honors them when no view overrides the instrument.
LATENCY_BUCKETS_S = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)

orders = meter.create_counter("meridian.orders", unit="{order}")
order_latency = meter.create_histogram(
    "meridian.order.latency", unit="s", explicit_bucket_boundaries_advisory=LATENCY_BUCKETS_S
)
matching_latency = meter.create_histogram(
    "meridian.matching.latency", unit="s", explicit_bucket_boundaries_advisory=LATENCY_BUCKETS_S
)
cache_hits = meter.create_counter("meridian.cache.hits")
cache_misses = meter.create_counter("meridian.cache.misses")
ratelimit_rejections = meter.create_counter("meridian.ratelimit.rejections")


def _observe_streams(_options) -> list[Observation]:
    # lazy import: fanout imports app.redis which imports this module
    from app.fanout import tick_hub

    return [Observation(tick_hub.active_streams)]


meter.create_observable_gauge(
    "meridian.sse.active_streams", callbacks=[_observe_streams]
)
