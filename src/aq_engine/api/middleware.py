import logging
import time
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

async def global_audit_and_exception_middleware(request: Request, call_next):
    """
    Enterprise middleware to inject request tracing, audit API performance,
    and sanitize unhandled exceptions to prevent stack-trace leakage.
    """
    request_id = str(uuid.uuid4())
    start_time = time.time()

    try:
        response = await call_next(request)
        process_time = time.time() - start_time

        logger.info(
            "Request completed",
            extra={
                "event": "request_completed",
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_seconds": round(process_time, 3),
                "operation": "http_request",
                "source": "fastapi",
            },
        )

        # Inject the trace ID back to the client for debugging cross-service
        response.headers["X-Request-ID"] = request_id
        return response

    except Exception as exc:
        process_time = time.time() - start_time
        logger.error(
            "Request failed",
            extra={
                "event": "request_failed",
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": 500,
                "duration_seconds": round(process_time, 3),
                "operation": "http_request",
                "source": "fastapi",
                "error": str(exc),
                "exception_type": type(exc).__name__,
            },
            exc_info=True,
        )

        # Sanitize output to prevent leaking internal backend logic to clients
        return JSONResponse(
            status_code=500,
            headers={"X-Request-ID": request_id},
            content={
                "error": "Internal Server Error",
                "request_id": request_id,
                "message": "An unexpected system error occurred. Please provide the request_id to support."
            }
        )
