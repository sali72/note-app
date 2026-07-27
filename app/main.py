import asyncio
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.ai.api.routes import mirror as mirror_router
from app.ai.api.routes import llm_admin as llm_admin_router
from app.auth.api.routes import auth as auth_router
from app.auth.api.routes import google as google_router
from app.ai.api.routes import chat as chat_router
from app.chat.api.routes import chat_rest as chat_rest_router
from app.core.deps.database import get_client, init_database
from app.core.deps.settings import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.rate_limit import limiter, configure_limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from app.journals.api.routes import journals as journals_router
from app.journals.api.routes import tags as tags_router
from app.feedback.api.routes import feedback as feedback_router

# Configure logging
configure_logging()
logger = get_logger(__name__)

# Initialize Sentry error monitoring
from app.core.error_monitoring import init_sentry
settings = get_settings()
init_sentry(
    dsn=settings.sentry_dsn,
    environment=settings.environment,
    release=settings.app_version,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    Handles startup and shutdown events.
    """
    # Startup
    settings = get_settings()
    logger.info(
        "application_startup",
        environment=settings.environment,
        database=settings.database_name,
    )

    # Retry connecting to MongoDB with exponential backoff
    max_retries = 10
    base_delay = 2
    last_exception = None
    for attempt in range(1, max_retries + 1):
        try:
            client = await init_database()
            last_exception = None
            break
        except Exception as e:
            last_exception = e
            if attempt < max_retries:
                delay = base_delay * (2 ** (attempt - 1))
                logger.warning(
                    "database_connection_retry",
                    attempt=attempt,
                    max_retries=max_retries,
                    delay=delay,
                    error=str(e),
                )
                logger.info("waiting_for_mongodb", attempt=attempt, max_retries=max_retries, delay=delay)
                await asyncio.sleep(delay)
    if last_exception:
        logger.error("database_connection_failed", error=str(last_exception))
        from app.core.error_monitoring import capture_exception
        capture_exception(
            last_exception,
            {"context": "database_connection_retry_exhausted", "attempts": max_retries},
        )
        raise last_exception

    logger.info("database_connected", database=settings.database_name)
    logger.info("application_started", environment=settings.environment)

    yield

    # Shutdown
    import sentry_sdk
    sentry_sdk.add_breadcrumb(
        message="application_shutdown",
        category="lifecycle",
        level="info",
    )
    client.close()
    logger.info("application_shutdown")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    from app.core.middleware import RequestLoggingMiddleware, SecurityHeadersMiddleware
    
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="AI-boosted Journaling API with focus on self-knowledge",
        lifespan=lifespan,
    )

    # Security headers middleware
    app.add_middleware(SecurityHeadersMiddleware)

    # Request logging middleware
    app.add_middleware(RequestLoggingMiddleware)

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Rate limiting — slowapi
    configure_limiter(settings)
    app.state.limiter = limiter

    if settings.rate_limit_enabled:
        import re
        from slowapi.errors import RateLimitExceeded as SlowapiRateLimitExceeded
        from fastapi.responses import JSONResponse
        @app.exception_handler(SlowapiRateLimitExceeded)
        async def rate_limit_handler(request, exc):
            detail = str(exc)
            match = re.search(r'per\s+(\d+)\s+(second|minute|hour)', detail)
            if match:
                count = int(match.group(1))
                unit = match.group(2)
                multiplier = {"second": 1, "minute": 60, "hour": 3600}
                retry_after = str(count * multiplier[unit])
            else:
                retry_after = "60"
            return JSONResponse(
                status_code=429,
                content={"detail": detail},
                headers={"Retry-After": retry_after},
            )

        app.add_middleware(SlowAPIMiddleware)

    # Global handler to mask internal details on 5xx
    from starlette.exceptions import HTTPException as StarletteHTTPException
    @app.exception_handler(Exception)
    async def global_exception_handler(request, exc):
        if isinstance(exc, StarletteHTTPException):
            raise exc
        logger.error("unhandled_exception", error=str(exc), error_type=type(exc).__name__)
        import sentry_sdk
        sentry_sdk.set_context("request", {
            "method": request.method,
            "url": str(request.url),
            "path": request.url.path,
            "query": str(request.url.query),
            "client_ip": request.client.host if request.client else None,
        })
        sentry_sdk.capture_exception(exc)
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    # Register routers
    app.include_router(auth_router.router, prefix="/api/v0")
    app.include_router(google_router.router, prefix="/api/v0")
    app.include_router(journals_router.router, prefix="/api/v0")
    app.include_router(mirror_router.router, prefix="/api/v0")
    app.include_router(llm_admin_router.router, prefix="/api/v0")
    app.include_router(chat_router.router, prefix="/api/v0")
    app.include_router(chat_rest_router.router, prefix="/api/v0")
    app.include_router(tags_router.router, prefix="/api/v0")
    app.include_router(feedback_router.router, prefix="/api/v0")

    # Dev-only memory management routes
    if not settings.is_production:
        from app.memory.api.routes import user_model as user_model_router
        app.include_router(user_model_router.router, prefix="/api/v0")
        logger.info("memory_dev_routes_enabled")

    @app.get("/", tags=["health"])
    async def root():
        """Root endpoint - health check."""
        return {
            "status": "healthy",
            "app": settings.app_name,
            "version": settings.app_version,
            "environment": settings.environment,
        }

    @app.get("/health", tags=["health"])
    async def health_check():
        """Health check endpoint with database connectivity check."""
        try:
            # Check database connection
            client = await get_client()
            await client.admin.command('ping')
            
            return {
                "status": "healthy",
                "database": "connected",
                "app": settings.app_name,
                "version": settings.app_version
            }
        except Exception as e:
            logger.error("health_check_failed", error=str(e))
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=503,
                content={
                    "status": "unhealthy",
                    "database": "disconnected",
                    "error": str(e)
                }
            )

    return app


app = create_app()
