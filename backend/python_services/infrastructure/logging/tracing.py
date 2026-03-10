from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

try:
    from opentelemetry import trace as otel_trace
except Exception:
    otel_trace = None


@dataclass(frozen=True)
class TracerHandle:
    name: str
    enabled: bool


def get_tracer(name: str = "lexicon_pipeline") -> TracerHandle:
    return TracerHandle(name=name, enabled=otel_trace is not None)


@contextmanager
def start_span(tracer: TracerHandle, span_name: str) -> Iterator[None]:
    if not tracer.enabled or otel_trace is None:
        yield
        return
    otel = otel_trace.get_tracer(tracer.name)
    with otel.start_as_current_span(span_name):
        yield
