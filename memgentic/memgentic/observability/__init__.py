"""Optional observability layer — opt-in via `pip install memgentic[observability]`.

Provides tracing, metrics, and structured timing instrumentation. When the
observability extras are not installed (or when ``init_observability`` is not
called with ``enabled=True``), all functions become no-ops with effectively
zero overhead.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import Any

try:
    from opentelemetry import metrics, trace
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
        OTLPMetricExporter,
    )
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
        OTLPSpanExporter,
    )
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    _HAS_OTEL = True
except ImportError:  # pragma: no cover - exercised in no-extras envs
    _HAS_OTEL = False
    trace = None  # type: ignore[assignment]
    metrics = None  # type: ignore[assignment]
    TracerProvider = None  # type: ignore[assignment,misc]
    BatchSpanProcessor = None  # type: ignore[assignment,misc]
    MeterProvider = None  # type: ignore[assignment,misc]
    PeriodicExportingMetricReader = None  # type: ignore[assignment,misc]
    OTLPSpanExporter = None  # type: ignore[assignment,misc]
    OTLPMetricExporter = None  # type: ignore[assignment,misc]


_tracer: Any = None
_meter: Any = None
_counters: dict[str, Any] = {}
_histograms: dict[str, Any] = {}


def init_observability(
    service_name: str = "memgentic",
    otlp_endpoint: str | None = None,
    enabled: bool = True,
) -> None:
    """Initialize OpenTelemetry tracing + metrics.

    This is a no-op when:
    - The ``[observability]`` extras are not installed, OR
    - ``enabled`` is ``False``.

    Safe to call multiple times; subsequent calls re-initialize providers.
    """
    global _tracer, _meter
    if not _HAS_OTEL or not enabled:
        return

    try:
        provider = TracerProvider()
        if otlp_endpoint:
            provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{otlp_endpoint}/v1/traces"))
            )
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer(service_name)

        readers = []
        if otlp_endpoint:
            readers.append(
                PeriodicExportingMetricReader(
                    OTLPMetricExporter(endpoint=f"{otlp_endpoint}/v1/metrics"),
                    export_interval_millis=60000,
                )
            )
        meter_provider = MeterProvider(metric_readers=readers)
        metrics.set_meter_provider(meter_provider)
        _meter = metrics.get_meter(service_name)
    except Exception:  # pragma: no cover - defensive: never break the host app
        _tracer = None
        _meter = None


@contextlib.contextmanager
def trace_span(name: str, **attributes: Any) -> Iterator[None]:
    """Context manager that creates a span if tracing is enabled; no-op otherwise."""
    if _tracer is None:
        yield
        return
    try:
        with _tracer.start_as_current_span(name) as span:
            try:
                for k, v in attributes.items():
                    span.set_attribute(k, v)
            except Exception:  # pragma: no cover
                pass
            yield
    except Exception:  # pragma: no cover - never break the host app
        yield


def record_counter(name: str, value: int = 1, **labels: Any) -> None:
    """Record a counter metric. No-op if not initialized."""
    if _meter is None:
        return
    try:
        if name not in _counters:
            _counters[name] = _meter.create_counter(name)
        _counters[name].add(value, attributes=labels)
    except Exception:  # pragma: no cover
        pass


def record_histogram(name: str, value: float, **labels: Any) -> None:
    """Record a histogram observation. No-op if not initialized."""
    if _meter is None:
        return
    try:
        if name not in _histograms:
            _histograms[name] = _meter.create_histogram(name)
        _histograms[name].record(value, attributes=labels)
    except Exception:  # pragma: no cover
        pass


__all__ = [
    "init_observability",
    "trace_span",
    "record_counter",
    "record_histogram",
]
