from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sys
import types

import pytest

from backend.python_services.infrastructure import logging as logging_api
from backend.python_services.infrastructure.logging import app_logger, file_logger, json_logger, metrics, tracing


@pytest.fixture
def isolated_root_logger() -> logging.Logger:
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level
    original_propagate = root.propagate
    original_configured = app_logger._CONFIGURED_LOG_PATH

    root.handlers = []
    root.setLevel(logging.NOTSET)
    root.propagate = True
    app_logger._CONFIGURED_LOG_PATH = None
    try:
        yield root
    finally:
        for handler in list(root.handlers):
            root.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass
        root.handlers = original_handlers
        root.setLevel(original_level)
        root.propagate = original_propagate
        app_logger._CONFIGURED_LOG_PATH = original_configured


def test_to_serializable_supports_collection_and_isoformat_paths() -> None:
    class _BrokenIso:
        def isoformat(self) -> str:
            raise RuntimeError("broken")

    assert app_logger._to_serializable({"a", "b"}) in (["a", "b"], ["b", "a"])
    assert app_logger._to_serializable(("x", "y")) == ["x", "y"]
    assert app_logger._to_serializable(datetime(2026, 3, 3, tzinfo=timezone.utc)).startswith("2026-03-03")
    assert app_logger._to_serializable(_BrokenIso()).startswith("<")


def test_structured_json_formatter_includes_traceback() -> None:
    formatter = app_logger._StructuredJsonFormatter()
    try:
        raise ValueError("boom")
    except ValueError:
        exc_info = sys.exc_info()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.ERROR,
            pathname=__file__,
            lineno=42,
            msg="failure",
            args=(),
            exc_info=exc_info,
        )
        formatted = formatter.format(record)
    payload = json.loads(formatted)
    assert payload["level"] == "ERROR"
    assert payload["message"] == "failure"
    assert payload["logger"] == "test.logger"
    assert "traceback" in payload


def test_configure_app_logger_sets_handlers_and_reuses_configuration(
    isolated_root_logger: logging.Logger,
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "runtime" / "app.log"
    root1 = app_logger.configure_app_logger(
        log_path,
        level=logging.WARNING,
        max_bytes=0,
        backup_count=0,
    )
    assert root1 is isolated_root_logger
    assert len(root1.handlers) == 2
    assert root1.level == logging.WARNING
    assert app_logger._CONFIGURED_LOG_PATH == log_path.resolve()

    root2 = app_logger.configure_app_logger(log_path, level=logging.DEBUG)
    assert root2 is isolated_root_logger
    assert len(root2.handlers) == 2
    assert root2.level == logging.DEBUG


def test_configure_app_logger_tolerates_handler_close_errors(
    isolated_root_logger: logging.Logger,
    tmp_path: Path,
) -> None:
    class _BadHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            _ = record

        def close(self) -> None:
            raise RuntimeError("close failed")

    isolated_root_logger.addHandler(_BadHandler())
    app_logger.configure_app_logger(tmp_path / "app.log")
    assert len(isolated_root_logger.handlers) == 2


def test_app_logging_service_emits_and_closes(
    isolated_root_logger: logging.Logger,
    tmp_path: Path,
) -> None:
    service = app_logger.AppLoggingService(tmp_path / "service.log", logger_name="runtime.service")
    service.info(" info msg ")
    service.warning(" warn msg ")
    service.error(" err msg ")

    close_calls = {"flush": 0, "close": 0}

    class _FailingHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            _ = record

        def flush(self) -> None:
            close_calls["flush"] += 1
            raise RuntimeError("flush failed")

    class _RotatingLike(app_logger.RotatingFileHandler):
        def __init__(self, filename: Path) -> None:
            super().__init__(filename=filename, maxBytes=1, backupCount=1, encoding="utf-8")

        def close(self) -> None:
            close_calls["close"] += 1
            raise RuntimeError("close failed")

    isolated_root_logger.addHandler(_FailingHandler())
    isolated_root_logger.addHandler(_RotatingLike(tmp_path / "closer.log"))
    service.close()
    assert close_calls["flush"] >= 1
    assert close_calls["close"] >= 1


def test_file_logging_service_writes_lines(tmp_path: Path) -> None:
    path = tmp_path / "logs" / "plain.log"
    service = file_logger.FileLoggingService(path)
    service.info(" info ")
    service.warning(" warn ")
    service.error(" err ")
    assert service.close() is None

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert "\tINFO\tinfo" in lines[0]
    assert "\tWARNING\twarn" in lines[1]
    assert "\tERROR\terr" in lines[2]


def test_json_logger_get_logger_is_idempotent_and_logs_event() -> None:
    logger = json_logger.get_logger("runtime.json")
    same_logger = json_logger.get_logger("runtime.json")
    assert logger is same_logger

    class _BrokenIso:
        def isoformat(self) -> str:
            raise RuntimeError("nope")

    captured_messages: list[str] = []

    class _CaptureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured_messages.append(record.getMessage())

    capture_handler = _CaptureHandler()
    logger.addHandler(capture_handler)
    try:
        json_logger.log_event(
            logger,
            event="pipeline.step",
            value_set={"a", "b"},
            value_tuple=("x", "y"),
            value_iso=_BrokenIso(),
        )
    finally:
        logger.removeHandler(capture_handler)

    assert len(captured_messages) == 1
    payload = json.loads(captured_messages[0])
    assert payload["event"] == "pipeline.step"
    assert sorted(payload["value_set"]) == ["a", "b"]
    assert payload["value_tuple"] == ["x", "y"]
    assert isinstance(payload["value_iso"], str)


def test_metrics_registry_snapshot_and_global_registry() -> None:
    registry = metrics.MetricsRegistry()
    registry.inc("requests")
    registry.inc("requests", 2)
    registry.observe("latency_ms", 5.0)
    registry.observe("latency_ms", 15.0)
    snap = registry.snapshot()

    assert snap["counters"] == {"requests": 3}
    hist = snap["histograms"]["latency_ms"]
    assert hist["count"] == 2
    assert hist["min_value"] == pytest.approx(5.0)
    assert hist["max_value"] == pytest.approx(15.0)
    assert hist["avg_value"] == pytest.approx(10.0)

    assert metrics.get_metrics_registry() is metrics._METRICS_REGISTRY


def test_tracing_handles_disabled_and_enabled_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tracing, "otel_trace", None)
    tracer = tracing.get_tracer("runtime.trace")
    assert tracer.enabled is False
    with tracing.start_span(tracer, "span.disabled"):
        pass

    calls: dict[str, object] = {}

    class _FakeSpan:
        def __enter__(self) -> None:
            calls["entered"] = True
            return None

        def __exit__(self, exc_type, exc, tb) -> bool:  # type: ignore[no-untyped-def]
            calls["exited"] = True
            return False

    class _FakeTracer:
        def start_as_current_span(self, span_name: str) -> _FakeSpan:
            calls["span_name"] = span_name
            return _FakeSpan()

    fake_otel = types.SimpleNamespace(get_tracer=lambda name: _FakeTracer())
    monkeypatch.setattr(tracing, "otel_trace", fake_otel)
    tracer_enabled = tracing.get_tracer("runtime.trace")
    assert tracer_enabled.enabled is True
    with tracing.start_span(tracer_enabled, "span.enabled"):
        calls["inside"] = True

    assert calls["span_name"] == "span.enabled"
    assert calls["inside"] is True
    assert calls["entered"] is True
    assert calls["exited"] is True


def test_logging_package_exports_public_api() -> None:
    assert callable(logging_api.configure_app_logger)
    assert callable(logging_api.get_app_logger)
    assert callable(logging_api.get_logger)
    assert callable(logging_api.log_event)
    assert callable(logging_api.get_metrics_registry)
    assert callable(logging_api.get_tracer)
    assert callable(logging_api.start_span)
