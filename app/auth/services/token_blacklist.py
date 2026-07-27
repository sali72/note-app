from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis

from app.core.logging import get_logger

logger = get_logger(__name__)


class TokenBlacklistService:
    """Redis-backed JWT blacklist for immediate logout & session revocation.

    Graceful degradation:
    * If Redis is unavailable or unconfigured, falls back to in-memory TTL storage
      so blacklisting and instant revocation work reliably in dev & test environments.
    """

    _memory_storage: dict[str, float] = {}

    def __init__(self, redis_url: Optional[str]):
        self._redis: Optional[aioredis.Redis] = None
        self._redis_url = redis_url
        self._enabled = redis_url is not None
        self._disabled = False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_redis(self) -> Optional[aioredis.Redis]:
        if self._disabled or not self._enabled:
            return None
        if self._redis is None:
            try:
                self._redis = await aioredis.from_url(
                    self._redis_url,
                    decode_responses=True,
                    socket_connect_timeout=2,
                )
            except Exception as exc:
                logger.warning("redis_connection_failed", error=str(exc))
                self._disabled = True
                return None
        return self._redis

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def blacklist(self, jti: str, ttl_seconds: int) -> None:
        """Add a JWT ID or family_id to the blacklist with the given TTL."""
        r = await self._get_redis()
        if r is None:
            self._memory_storage[jti] = datetime.now(timezone.utc).timestamp() + ttl_seconds
            return
        try:
            await r.setex(f"jwt:blacklist:{jti}", ttl_seconds, "1")
        except Exception as exc:
            logger.warning("blacklist_set_failed", jti=jti, error=str(exc))
            self._memory_storage[jti] = datetime.now(timezone.utc).timestamp() + ttl_seconds

    async def is_blacklisted(self, jti: str) -> bool:
        """Return ``True`` if the JWT ID or family_id is currently blacklisted."""
        r = await self._get_redis()
        if r is None:
            exp = self._memory_storage.get(jti)
            if not exp:
                return False
            if datetime.now(timezone.utc).timestamp() > exp:
                del self._memory_storage[jti]
                return False
            return True
        try:
            return bool(await r.exists(f"jwt:blacklist:{jti}"))
        except Exception as exc:
            logger.warning("blacklist_check_failed", jti=jti, error=str(exc))
            exp = self._memory_storage.get(jti)
            return bool(exp and datetime.now(timezone.utc).timestamp() <= exp)

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.close()
