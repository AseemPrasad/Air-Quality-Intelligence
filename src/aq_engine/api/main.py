
"""FastAPI application for Air Quality Intelligence Platform."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
import re

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from aq_engine.api.middleware import global_audit_and_exception_middleware
from aq_engine.api.observations import router as observations_router
from aq_engine.common.logger import get_logger, load_logging_config


__version__ = "0.1.0"

logger = get_logger(__name__)


class HealthStatus:
    """Track application component health."""

    def __init__(self):
        self.database_ok = False
        self.models_ok = False
        self.startup_time = None

    @property
    def is_healthy(self):
        return self.database_ok and self.models_ok

    def to_dict(self):
        return {
            "status": "healthy" if self.is_healthy else "degraded",
            "database": "ok" if self.database_ok else "error",
            "models": "ok" if self.models_ok else "error",
            "startup_time": (
                self.startup_time.isoformat()
                if self.startup_time else None
            ),
        }


health_status = HealthStatus()


def utc_now():
    """Return current UTC timestamp."""

    return datetime.now(timezone.utc)


def validate_location_id(location_id: str) -> str:
    """Validate location identifier."""

    location_id = location_id.strip().lower()

    if not location_id:
        raise ValueError("location_id cannot be empty")

    if not re.fullmatch(r"[a-z0-9_-]{1,100}", location_id):
        raise ValueError("Invalid location_id format")

    return location_id


def create_error_response(
    request: Request,
    message: str,
    code: int,
):
    """Create a standardized error response."""

    return JSONResponse(
        status_code=code,
        content={
            "error": message,
            "request_id": getattr(
                request.state, "request_id", "unknown"
            ),
            "timestamp": utc_now().isoformat(),
        },
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown."""

    health_status.database_ok = False
    health_status.models_ok = False
    health_status.startup_time = None

    Path("data/logs").mkdir(parents=True, exist_ok=True)
    load_logging_config("configs/logging.yaml")

    logger.info("Starting Air Quality Intelligence Platform")

    try:
        # TODO: Initialize the actual database connection here.
        logger.info("Database initialization pending.")

        # TODO: Load and validate the actual ML model registry here.
        logger.info("ML model initialization pending.")

        # Do not mark unavailable services as healthy.
        health_status.database_ok = False
        health_status.models_ok = False

        health_status.startup_time = utc_now()

        app.state.health_status = health_status

        logger.info("Application startup completed.")

        yield

    except Exception:
        logger.exception("Application lifecycle error")
        raise

    finally:
        logger.info("Shutting down Air Quality Intelligence Platform")

        try:
            # TODO: Close database connections.
            # TODO: Release loaded model resources.
            logger.info("Resource cleanup completed.")

        except Exception:
            logger.exception("Resource cleanup failed")

        finally:
            health_status.database_ok = False
            health_status.models_ok = False

            logger.info("Application shutdown completed.")


app = FastAPI(
    title="Air Quality Intelligence Platform",
    description="PM2.5 forecasting with ML and baseline models",
    version=__version__,
    lifespan=lifespan,
)


# Register observation routes
app.include_router(observations_router)


# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:8501",
        "http://localhost:8000",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)


# Register audit middleware
app.middleware("http")(global_audit_and_exception_middleware)


# Exception handlers
@app.exception_handler(ValueError)
async def value_error_handler(
    request: Request,
    exc: ValueError,
):
    """Handle invalid input."""

    logger.warning("Invalid input: %s", exc)

    return create_error_response(
        request,
        str(exc),
        status.HTTP_400_BAD_REQUEST,
    )


@app.exception_handler(Exception)
async def generic_exception_handler(
    request: Request,
    exc: Exception,
):
    """Handle unexpected exceptions."""

    logger.exception("Unhandled application exception")

    return create_error_response(
        request,
        "Internal server error",
        status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


# Health endpoint
@app.get(
    "/health",
    tags=["Health"],
    summary="Health check",
    description="Check application health status",
    response_model=dict,
)
async def health_check(request: Request):
    """Return application health information."""

    result = {
        "version": __version__,
        "timestamp": utc_now().isoformat(),
        **health_status.to_dict(),
    }

    logger.debug(
        "Health check requested",
        extra={
            "request_id": getattr(
                request.state, "request_id", "unknown"
            )
        },
    )

    return JSONResponse(
        status_code=(
            status.HTTP_200_OK
            if health_status.is_healthy
            else status.HTTP_503_SERVICE_UNAVAILABLE
        ),
        content=result,
    )


# Root endpoint
@app.get(
    "/",
    tags=["Root"],
    summary="API information",
    description="Get platform information",
)
async def root():
    """Return basic API information."""

    return {
        "name": "Air Quality Intelligence Platform",
        "version": __version__,
        "docs": "/docs",
        "health": "/health",
    }


# Prediction endpoint
@app.get(
    "/predictions/{location_id}",
    tags=["Predictions"],
    summary="Multi-horizon predictions",
    description="Get multi-horizon PM2.5 predictions for a location",
)
async def get_predictions(
    location_id: str,
    request: Request,
):
    """Return PM2.5 predictions for a location."""

    location_id = validate_location_id(location_id)

    # Actual ML model integration is required here.
    # Do not return fabricated predictions as real forecasts.
    logger.warning(
        "Prediction service is not configured for location: %s",
        location_id,
    )

    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "error": "Prediction service is currently unavailable.",
            "location_id": location_id,
            "request_id": getattr(
                request.state, "request_id", "unknown"
            ),
            "timestamp": utc_now().isoformat(),
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "aq_engine.api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )

