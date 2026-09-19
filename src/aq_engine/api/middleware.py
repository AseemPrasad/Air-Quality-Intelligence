from fastapi import Request
from fastapi.responses import JSONResponse
import logging
import time
import uuid

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
            f"AUDIT [{request_id}] {request.method} {request.url.path} "
            f"- Status: {response.status_code} - Time: {process_time:.3f}s"
        )
        
        # Inject the trace ID back to the client for debugging cross-service
        response.headers["X-Request-ID"] = request_id
        return response
        
    except Exception as exc:
        process_time = time.time() - start_time
        logger.error(
            f"FAIL [{request_id}] {request.method} {request.url.path} "
            f"- Time: {process_time:.3f}s - Error: {str(exc)}", 
            exc_info=True
        )
        
        # Sanitize output to prevent leaking internal backend logic to clients
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal Server Error",
                "request_id": request_id,
                "message": "An unexpected system error occurred. Please provide the request_id to support."
            }
        )
