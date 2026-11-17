
import json
import logging
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pythonjsonlogger.jsonlogger import JsonFormatter

from aq_engine.api.main import app as api_app
from aq_engine.api.middleware import global_audit_and_exception_middleware


@pytest.fixture
def middleware_app():
    app = FastAPI()
    app.middleware("http")(global_audit_and_exception_middleware)

    @app.get("/success")
    async def success(request: Request):
        return {"request_id": request.state.request_id}

    @app.get("/error")
    async def error():
        raise RuntimeError("Something went wrong internally")

    return app


def test_middleware_successful_request(middleware_app, caplog):
    caplog.set_level(logging.INFO, logger="aq_engine.api.middleware")

    response = TestClient(middleware_app).get("/success")

    assert response.status_code == 200
    request_id = response.headers["X-Request-ID"]
    assert response.json()["request_id"] == request_id

    record = next(
        (
            item for item in caplog.records
            if item.getMessage() == "Request completed"
        ),
        None,
    )

    assert record is not None
    assert record.event == "request_completed"
    assert record.request_id == request_id
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
    assert data["request_id"] == response.headers["X-Request-ID"]
    assert "An unexpected system error occurred" in data["message"]


def test_api_registers_audit_middleware_and_starts_with_json_logging():
    with TestClient(api_app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["X-Request-ID"]


def test_logging_config_serializes_audit_fields_as_json():
    config_path = Path(__file__).parents[2] / "configs" / "logging.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
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

    fields = {
        "event": "request_completed",
        "request_id": "test-request-id",
        "method": "GET",
        "path": "/health",
        "status": 200,
        "duration_seconds": 0.125,
        "operation": "http_request",
        "source": "fastapi",
    }

    for key, value in fields.items():
        setattr(record, key, value)

    logged = json.loads(formatter.format(record))

    for key, value in fields.items():
        assert logged[key] == value
