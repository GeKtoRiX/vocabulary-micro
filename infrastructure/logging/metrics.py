from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from threading import RLock
from typing import Dict, List


@dataclass(frozen=True)
class HistogramBucket:
    metric: str
    count: int
    min_value: float
    max_value: float
    avg_value: float


class MetricsRegistry:
    def __init__(self) -> None:
        self._counters: Counter[str] = Counter()
        self._histograms: Dict[str, List[float]] = defaultdict(list)
        self._lock = RLock()

    def inc(self, metric: str, value: int = 1) -> None:
        with self._lock:
            self._counters[metric] += value

    def observe(self, metric: str, value: float) -> None:
        with self._lock:
            self._histograms[metric].append(float(value))

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            counters = dict(self._counters)
            histograms = {
                metric: HistogramBucket(
                    metric=metric,
                    count=len(values),
                    min_value=min(values) if values else 0.0,
                    max_value=max(values) if values else 0.0,
                    avg_value=(sum(values) / len(values)) if values else 0.0,
                )
                for metric, values in self._histograms.items()
            }
        return {
            "counters": counters,
            "histograms": {key: value.__dict__ for key, value in histograms.items()},
        }


_METRICS_REGISTRY = MetricsRegistry()


def get_metrics_registry() -> MetricsRegistry:
    return _METRICS_REGISTRY
