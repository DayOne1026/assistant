"""12 OTel 追踪（蓝图 12 core/telemetry.py）。

setup_telemetry 注册请求 span 中间件；trace 给关键路径（AgentRunner.run、检索、OAuth 调用）包 span。
otel_enabled 关时走 OTel 默认 no-op provider，span 仍创建但不导出，成本近零。
"""

from contextlib import contextmanager
from typing import Iterator

from fastapi import FastAPI, Request
from opentelemetry import trace as otel_trace
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import get_settings
from app.core.logging import redact


@contextmanager
def trace(span_name: str, **attrs) -> Iterator[otel_trace.Span]:
    """上下文管理器：给关键路径包 span；属性值经 redact（user_id 脱敏后落属性）。"""
    with otel_trace.get_tracer(__name__).start_as_current_span(span_name) as span:
        for key, value in attrs.items():
            span.set_attribute(key, redact(str(value)))
        yield span


class _TraceMiddleware(BaseHTTPMiddleware):
    """每个请求一个 span：方法 + 路径 + 状态码。"""

    async def dispatch(self, request: Request, call_next):
        span = otel_trace.get_tracer(__name__).start_span(f"{request.method} {request.url.path}")
        try:
            response = await call_next(request)
            span.set_attribute("http.status_code", response.status_code)
        finally:
            span.end()
        return response


def setup_telemetry(app: FastAPI) -> None:
    """注册请求 span 中间件；otel_enabled 时配 ConsoleSpanExporter（dev 调试用）。"""
    if get_settings().otel_enabled:
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

        provider = TracerProvider(resource=Resource.create(
            {"service.name": get_settings().otel_service_name},
        ))
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        otel_trace.set_tracer_provider(provider)
    app.add_middleware(_TraceMiddleware)
