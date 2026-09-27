"""Simple in-memory rate limiting for API endpoints."""

import time
import logging
from collections import defaultdict
from typing import Dict, Tuple
from fastapi import Request, HTTPException, status


logger = logging.getLogger(__name__)


class RateLimiter:
    """In-memory rate limiter using token bucket algorithm.
    
    Tracks requests per IP address with configurable limits.
    Suitable for single-instance deployments; use Redis for distributed systems.
    """

    def __init__(self, requests_per_minute: int = 100):
        """Initialize rate limiter.
        
        Args:
            requests_per_minute: Maximum requests allowed per minute per IP.
        """
        self.requests_per_minute = requests_per_minute
        self.window_seconds = 60
        # Store: {ip: [(timestamp1, timestamp2, ...)]}
        self.requests: Dict[str, list[float]] = defaultdict(list)
        
    def check_rate_limit(self, client_ip: str) -> Tuple[bool, int]:
        """Check if request is within rate limit.
        
        Args:
            client_ip: Client IP address.
            
        Returns:
            Tuple of (is_allowed, remaining_requests)
        """
        current_time = time.time()
        cutoff_time = current_time - self.window_seconds
        
        # Remove expired timestamps
        self.requests[client_ip] = [
            ts for ts in self.requests[client_ip] 
            if ts > cutoff_time
        ]
        
        # Check limit
        request_count = len(self.requests[client_ip])
        if request_count >= self.requests_per_minute:
            return False, 0
            
        # Add current request
        self.requests[client_ip].append(current_time)
        remaining = self.requests_per_minute - request_count - 1
        
        return True, remaining
        
    def get_client_ip(self, request: Request) -> str:
        """Extract client IP from request.
        
        Checks X-Forwarded-For header for proxy/load balancer support.
        
        Args:
            request: FastAPI request object.
            
        Returns:
            Client IP address.
        """
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            # Take first IP if multiple proxies
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"
        
    async def __call__(self, request: Request):
        """Middleware call to check rate limit.
        
        Args:
            request: FastAPI request object.
            
        Raises:
            HTTPException: If rate limit exceeded.
        """
        client_ip = self.get_client_ip(request)
        allowed, remaining = self.check_rate_limit(client_ip)
        
        if not allowed:
            logger.warning(
                f"Rate limit exceeded for {client_ip}",
                extra={"client_ip": client_ip, "path": request.url.path}
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Maximum 100 requests per minute.",
                headers={"Retry-After": "60"}
            )
            
        # Add rate limit headers to response (done in middleware)
        request.state.rate_limit_remaining = remaining
