"""
cache.py — Optional Redis cache layer.
If Redis is unavailable the app runs fine — cache_get always returns None
and cache_set is a no-op.  This makes Redis a pure performance optimisation,
not a hard dependency.
"""
import json
from typing import Any, Optional

try:
    import redis.asyncio as aioredis
    _REDIS_AVAILABLE = True
except ImportError:
    _REDIS_AVAILABLE = False

from .config import get_settings

settings = get_settings()
_redis: Optional[Any] = None


async def _get_redis():
    global _redis
    if not _REDIS_AVAILABLE:
        return None
    if _redis is None:
        try:
            _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
            await _redis.ping()          # test connection once
        except Exception:
            _redis = None
    return _redis


async def cache_get(key: str) -> Any | None:
    r = await _get_redis()
    if r is None:
        return None
    try:
        value = await r.get(key)
        return json.loads(value) if value else None
    except Exception:
        return None


async def cache_set(key: str, value: Any, ttl: int = settings.cache_ttl_seconds) -> None:
    r = await _get_redis()
    if r is None:
        return
    try:
        await r.set(key, json.dumps(value), ex=ttl)
    except Exception:
        pass


async def cache_delete(key: str) -> None:
    r = await _get_redis()
    if r is None:
        return
    try:
        await r.delete(key)
    except Exception:
        pass
