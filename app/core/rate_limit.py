"""Rate limiting for API endpoints using slowapi + limits."""

from typing import Optional

from slowapi import Limiter
from starlette.requests import Request
from limits import RateLimitItemPerMinute

from app.core.logging import get_logger

logger = get_logger(__name__)


def custom_key_func(request: Request) -> str:
    """Key function for rate limiting.

    Priority:
    1. `request.state.user` — per-user key for authenticated requests
    2. `X-Real-IP` header — authoritative client IP set by nginx/Cloudflare
    3. `X-Forwarded-For` header — fallback for dev without nginx
    4. `request.client.host` — last resort
    """
    user = getattr(request.state, "user", None)
    if user is not None:
        return f"user:{user.id}"

    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip

    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()

    if request.client:
        return request.client.host

    return "unknown"


limiter = Limiter(
    key_func=custom_key_func,
    default_limits=["60/minute"],
)


def configure_limiter(settings):
    """Configure the rate limiter backend and respect the enabled toggle.

    In development/testing the default in-memory storage is used.
    In production with a Redis URL configured, we swap to Redis so that
    blue/green backend containers share the same rate limit state.
    """
    if not settings.rate_limit_enabled:
        limiter.enabled = False
        logger.info("rate_limiter_disabled")
        return

    if settings.is_production and settings.redis_url:
        from limits.storage import RedisStorage
        from limits.strategies import MovingWindowRateLimiter

        storage = RedisStorage(settings.redis_url)
        limiter.limiter = MovingWindowRateLimiter(storage)
        logger.info("rate_limiter_redis", url=settings.redis_url)
    else:
        logger.info("rate_limiter_memory")


def check_rate_limit(
    key: str, max_requests: int = 5,
) -> tuple[bool, Optional[float]]:
    """Programmatic rate check using the shared backend.

    Used for programmatic rate checks (slowapi decorators can't cover
    streaming endpoints and other non-standard flows).
    Returns (allowed, retry_after_seconds). retry_after is None when allowed.
    """
    allowed = limiter.limiter.hit(RateLimitItemPerMinute(max_requests), key)
    if not allowed:
        logger.warning("rate_limit_exceeded", key=key, limit=max_requests)
        return False, 60.0
    return True, None
