"""Unit tests for global_audit_and_exception_middleware in aq_engine.api.middleware."""

import json
import logging
from pathlib import Path

import pytest
import yaml
from aq_engine.api.main import app as api_app
from aq_engine.api.middleware import global_audit_and_exception_middleware
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pythonjsonlogger.jsonlogger import JsonFormatter


@pytest.fixture
def middleware_app():
    test_app = FastAPI()
    test_app.middleware("http")(global_audit_and_exception_middleware)

    @test_app.get("/success")
    async def success_endpoint(request: Request):
        return {"request_id": request.state.request_id}

    @test_app.get("/error")
    async def error_endpoint():
        raise RuntimeError("Something went wrong internally")

    return test_app


def test_middleware_successful_request(middleware_app, caplog):
    caplog.set_level(logging.INFO, logger="aq_engine.api.middleware")
    client = TestClient(middleware_app)
    response = client.get("/success")
    assert response.status_code == 200
    assert "X-Request-ID" in response.headers
    assert response.json()["request_id"] == response.headers["X-Request-ID"]

    record = next(record for record in caplog.records if record.getMessage() == "Request completed")
    assert record.event == "request_completed"
    assert record.request_id == response.headers["X-Request-ID"]
    assert record.method == "GET"
    assert record.path == "/success"
    assert record.status == 200
    assert record.duration_seconds >= 0
    assert record.operation == "http_request"
    assert record.source == "fastapi"


def test_middleware_catches_unhandled_exception(middleware_app):
    client = TestClient(middleware_app, raise_server_exceptions=False)
    response = client.get("/error")
    assert response.status_code == 500
    data = response.json()
    assert data["error"] == "Internal Server Error"
    assert "request_id" in data
    assert response.headers["X-Request-ID"] == data["request_id"]
    assert "An unexpected system error occurred" in data["message"]


def test_api_registers_audit_middleware_and_starts_with_json_logging():
    with TestClient(api_app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["X-Request-ID"]


def test_logging_config_serializes_audit_fields_as_json():
    config_path = Path(__file__).parents[2] / "configs" / "logging.yaml"
    config = yaml.safe_load(config_path.read_text())
    formatter_config = config["formatters"]["json"]
    formatter = JsonFormatter(
        fmt=formatter_config["fmt"],
        rename_fields=formatter_config["rename_fields"],
    )
    record = logging.LogRecord(
        name="aq_engine.api.middleware",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Request completed",
        args=(),
        exc_info=None,
    )
    for key, value in {
        "event": "request_completed",
        "request_id": "test-request-id",
        "method": "GET",
        "path": "/health",
        "status": 200,
        "duration_seconds": 0.125,
        "operation": "http_request",
        "source": "fastapi",
    }.items():
        setattr(record, key, value)

    logged = json.loads(formatter.format(record))
    assert logged["event"] == "request_completed"
    assert logged["request_id"] == "test-request-id"
    assert logged["duration_seconds"] == 0.125
