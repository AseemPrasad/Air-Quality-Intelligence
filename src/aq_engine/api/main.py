"""FastAPI application for Air Quality Intelligence Platform."""

import logging
import uuid
import time
from datetime import datetime, timezone
from typing import Callable

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

# Version info
__version__ = "0.1.0"


class HealthStatus:
    """Manage application health status."""

    def __init__(self):
        """Initialize health status."""
        self.database_ok = False
        self.models_ok = False
        self.startup_time = None

    def to_dict(self) -> dict:
        """Convert to response dict."""
        return {
            "status": "healthy" if (self.database_ok and self.models_ok) else "degraded",
            "database": "ok" if self.database_ok else "error",
            "models": "ok" if self.models_ok else "error",
            "startup_time": self.startup_time.isoformat() if self.startup_time else None,
        }


# Global health status
health_status = HealthStatus()


async def lifespan(app: FastAPI):
    """Manage application startup and shutdown."""
    # Startup
    logger.info("Starting Air Quality Intelligence Platform...")

    try:
        # Initialize database (placeholder)
        logger.info("Initializing database...")
        health_status.database_ok = True

        # Load model registry (placeholder)
        logger.info("Loading model registry...")
        health_status.models_ok = True

        health_status.startup_time = datetime.now(timezone.utc)
        logger.info("Application started successfully")
    except Exception as e:
        logger.error(f"Startup error: {e}")
        raise

    yield

    # Shutdown
    logger.info("Shutting down Air Quality Intelligence Platform...")

    try:
        # Close database connections (placeholder)
        logger.info("Closing database connections...")

        # Clean up resources (placeholder)
        logger.info("Cleaning up resources...")

        logger.info("Application shut down gracefully")
    except Exception as e:
        logger.error(f"Shutdown error: {e}")


# Create FastAPI app
app = FastAPI(
    title="Air Quality Intelligence Platform",
    description="PM2.5 forecasting with ML and baseline models",
    version=__version__,
    lifespan=lifespan,
)


# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",    # Dashboard
        "http://localhost:8501",    # Streamlit
        "http://localhost:8000",    # FastAPI docs
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Structured logging middleware
@app.middleware("http")
async def logging_middleware(request: Request, call_next: Callable) -> JSONResponse:
    """Log all requests with structured format."""
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id

    start_time = time.time()

    try:
        response = await call_next(request)
        duration = time.time() - start_time

        logger.info(
            f"Request completed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round(duration * 1000, 2),
            }
        )

        # Add request ID to response headers
        response.headers["X-Request-ID"] = request_id
        return response

    except Exception as e:
        duration = time.time() - start_time
        logger.error(
            f"Request failed: {str(e)}",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "duration_ms": round(duration * 1000, 2),
            },
            exc_info=True,
        )

        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "Internal server error",
                "request_id": request_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )


# Exception handler
@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    """Handle ValueError (invalid input)."""
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "error": str(exc),
            "request_id": getattr(request.state, "request_id", "unknown"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    """Handle generic exceptions."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "Internal server error",
            "request_id": getattr(request.state, "request_id", "unknown"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


# Health check endpoint
@app.get(
    "/health",
    tags=["Health"],
    summary="Health check",
    description="Check application health status",
    response_model=dict,
)
async def health_check(request: Request) -> dict:
    """Health check endpoint.

    Returns:
        Health status including database and model availability
    """
    response = {
        "version": __version__,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **health_status.to_dict(),
    }

    logger.debug("Health check requested", extra={
        "request_id": getattr(request.state, "request_id", "unknown"),
    })

    return response


# Root endpoint
@app.get(
    "/",
    tags=["Root"],
    summary="API info",
    description="Get API information",
)
async def root() -> dict:
    """Root endpoint with API information.

    Returns:
        Basic API information
    """
    return {
        "name": "Air Quality Intelligence Platform",
        "version": __version__,
        "docs": "/docs",
        "health": "/health",
    }


# Prediction endpoint (stub)
@app.get(
    "/predictions/{location_id}",
    tags=["Predictions"],
    summary="Multi-horizon predictions",
    description="Get multi-horizon PM2.5 predictions for a location",
)
async def get_predictions(
    location_id: str,
    request: Request,
) -> dict:
    """Get predictions for a location.

    Args:
        location_id: Location identifier (e.g., 'kolkata')

    Returns:
        Multi-horizon prediction data

    Raises:
        ValueError: If location_id is invalid
    """
    if not location_id:
        raise ValueError("location_id cannot be empty")

    # Stub response
    return {
        "location_id": location_id,
        "predictions": [
            {
                "horizon_minutes": 60,
                "predicted_pm25": 50.0,
                "lower_bound": 45.0,
                "upper_bound": 55.0,
                "confidence": 0.85,
            },
            {
                "horizon_minutes": 180,
                "predicted_pm25": 52.0,
                "lower_bound": 46.0,
                "upper_bound": 58.0,
                "confidence": 0.75,
            },
            {
                "horizon_minutes": 360,
                "predicted_pm25": 54.0,
                "lower_bound": 47.0,
                "upper_bound": 61.0,
                "confidence": 0.65,
            },
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "aq_engine.api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
