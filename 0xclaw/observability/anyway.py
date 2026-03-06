"""Anyway tracing bootstrap and span helpers (optional, env-driven)."""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager, nullcontext
from typing import Any, Iterator

logger = logging.getLogger(__name__)

_init_attempted = False
_enabled = False


def _get_traceloop_cls():
    from anyway.sdk import Traceloop

    return Traceloop


def _get_otel_trace_module():
    from opentelemetry import trace

    return trace


def _normalize_endpoint(raw: str) -> str:
    endpoint = (raw or "").strip()
    if not endpoint:
        return "https://trace-dev-collector.anyway.sh/"
    if "://" not in endpoint and endpoint.endswith(":4317"):
        # Preserve host:port style when users intentionally pass OTLP gRPC-style endpoint.
        return endpoint
    if "://" not in endpoint:
        return f"https://{endpoint}"
    return endpoint


def init_anyway_from_env(app_name_override: str | None = None) -> bool:
    """Initialize Anyway tracing once per process.

    Returns:
        True if tracing is enabled successfully, False otherwise.
    """
    global _init_attempted, _enabled

    if _init_attempted:
        return _enabled

    _init_attempted = True
    api_key = os.getenv("ANYWAY_API_KEY", "").strip()
    if not api_key:
        _enabled = False
        return False

    endpoint_raw = (
        os.getenv("ANYWAY_API_ENDPOINT")
        or os.getenv("ANYWAY_COLLECTOR")
        or "https://trace-dev-collector.anyway.sh/"
    )
    endpoint = _normalize_endpoint(endpoint_raw)
    app_name = (app_name_override or os.getenv("ANYWAY_APP_NAME") or "0xclaw").strip()
    metrics_enabled = os.getenv("ANYWAY_METRICS_ENABLED", "false").strip().lower() == "true"
    if not metrics_enabled:
        os.environ.setdefault("TRACELOOP_METRICS_ENABLED", "false")

    try:
        traceloop = _get_traceloop_cls()
        traceloop.init(
            app_name=app_name,
            api_endpoint=endpoint,
            headers={"Authorization": api_key},
        )
        _enabled = True
    except Exception as exc:  # pragma: no cover - exercised via tests with monkeypatch
        logger.warning("Anyway tracing init failed: %s", exc)
        _enabled = False

    return _enabled


@contextmanager
def workflow_span(name: str, attributes: dict[str, Any] | None = None) -> Iterator[Any]:
    """Create a workflow-level span when tracing is enabled."""
    if not _enabled:
        yield None
        return
    try:
        trace = _get_otel_trace_module()
        tracer = trace.get_tracer("0xclaw.anyway")
        with tracer.start_as_current_span(name) as span:
            span.set_attribute("traceloop.span.kind", "workflow")
            for k, v in (attributes or {}).items():
                if v is not None:
                    span.set_attribute(k, v)
            yield span
    except Exception as exc:  # pragma: no cover
        logger.warning("Anyway workflow span failed: %s", exc)
        with nullcontext(None) as span:
            yield span


@contextmanager
def task_span(name: str, attributes: dict[str, Any] | None = None) -> Iterator[Any]:
    """Create a task-level span when tracing is enabled."""
    if not _enabled:
        yield None
        return
    try:
        trace = _get_otel_trace_module()
        tracer = trace.get_tracer("0xclaw.anyway")
        with tracer.start_as_current_span(name) as span:
            span.set_attribute("traceloop.span.kind", "task")
            for k, v in (attributes or {}).items():
                if v is not None:
                    span.set_attribute(k, v)
            yield span
    except Exception as exc:  # pragma: no cover
        logger.warning("Anyway task span failed: %s", exc)
        with nullcontext(None) as span:
            yield span
