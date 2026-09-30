from opentelemetry import metrics
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from fastapi import Response

def setup_otel(app, service_name: str):
    # 1. Setup Resource
    resource = Resource(attributes={
        SERVICE_NAME: service_name
    })

    # 2. Initialize PrometheusMetricReader
    reader = PrometheusMetricReader()

    # 3. Setup MeterProvider
    provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(provider)

    # 4. Instrument FastAPI
    FastAPIInstrumentor.instrument_app(app)

    # 5. Add /metrics endpoint as a direct route
    @app.get("/metrics")
    @app.get("/metrics/")
    async def metrics_endpoint():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return metrics.get_meter(service_name)

# Custom metrics helpers
_meter = None

def get_meter():
    global _meter
    if _meter is None:
        _meter = metrics.get_meter("rs-agent-custom")
    return _meter

# Define some common metrics
def init_custom_metrics():
    meter = get_meter()
    
    # Counters
    meter.create_counter(
        "rs_transfers_total",
        description="Total number of file transfers initiated",
        unit="1"
    )
    
    meter.create_counter(
        "rs_packets_sent_total",
        description="Total number of RS packets sent",
        unit="1"
    )

    meter.create_counter(
        "rs_packets_lost_total",
        description="Total number of RS packets detected as lost (receivers)",
        unit="1"
    )

    meter.create_counter(
        "rs_packets_recovered_total",
        description="Total number of RS packets recovered via FEC",
        unit="1"
    )

    # Gauges
    meter.create_observable_gauge(
        "rs_active_transfers",
        callbacks=[], # Will need to attach a callback or update manually if using a Gauge
        description="Number of currently active transfers",
        unit="1"
    )
