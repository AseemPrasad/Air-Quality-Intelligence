"""Unit tests for global_audit_and_exception_middleware in aq_engine.api.middleware."""

import pytest
from aq_engine.api.middleware import global_audit_and_exception_middleware
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.testclient import TestClient


@pytest.fixture
def middleware_app():
    test_app = FastAPI()
    test_app.middleware("http")(global_audit_and_exception_middleware)

    @test_app.get("/success")
    async def success_endpoint():
        return PlainTextResponse("ok")

    @test_app.get("/error")
    async def error_endpoint():
        raise RuntimeError("Something went wrong internally")

    return test_app


def test_middleware_successful_request(middleware_app):
    client = TestClient(middleware_app)
    response = client.get("/success")
    assert response.status_code == 200
    assert response.text == "ok"
    assert "X-Request-ID" in response.headers


def test_middleware_catches_unhandled_exception(middleware_app):
    client = TestClient(middleware_app, raise_server_exceptions=False)
    response = client.get("/error")
    assert response.status_code == 500
    data = response.json()
    assert data["error"] == "Internal Server Error"
    assert "request_id" in data
    assert "An unexpected system error occurred" in data["message"]
