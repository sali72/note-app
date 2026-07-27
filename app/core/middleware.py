"""Middleware for request/response logging and monitoring."""
import time
import uuid
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from app.core.logging import get_logger

logger = get_logger(__name__)

SLOW_REQUEST_WARNING_MS = 5000


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware to add standard security headers to all responses."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Content-Security-Policy"] = "default-src 'self' 'unsafe-inline'; img-src 'self' data: https://fastapi.tiangolo.com"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware to log all requests and responses."""
    
    async def dispatch(self, request: Request, call_next):
        # Generate request ID
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        
        # Log request
        start_time = time.time()
        logger.info(
            "request_started",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            client=request.client.host if request.client else None
        )
        
        # Process request
        try:
            response = await call_next(request)
            
            # Calculate duration
            duration = time.time() - start_time
            duration_ms = round(duration * 1000, 2)
            
            # Log response
            logger.info(
                "request_completed",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=duration_ms,
            )
            
            # Report slow requests to Sentry
            if duration_ms > SLOW_REQUEST_WARNING_MS:
                import sentry_sdk
                sentry_sdk.set_context("slow_request", {
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": duration_ms,
                    "status_code": response.status_code,
                    "request_id": request_id,
                })
                sentry_sdk.capture_message(
                    f"Slow request: {request.method} {request.url.path} ({duration_ms}ms)",
                    level="warning",
                )
            
            # Add request ID to response headers
            response.headers["X-Request-ID"] = request_id
            
            return response
            
        except Exception as e:
            # Log error
            duration = time.time() - start_time
            duration_ms = round(duration * 1000, 2)
            logger.error(
                "request_failed",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                error=str(e),
                duration_ms=duration_ms,
            )
            raise
