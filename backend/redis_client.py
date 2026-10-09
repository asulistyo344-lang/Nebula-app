import redis.asyncio as aioredis
from config import settings

redis_pool = None

async def get_redis() -> aioredis.Redis:
    global redis_pool
    if redis_pool is None:
        redis_pool = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
    return redis_pool

async def close_redis():
    global redis_pool
    if redis_pool:
        await redis_pool.close()

# ── Quota helpers ────────────────────────────────────────────────

FREE_DAILY_LIMIT = 4

async def get_quota_used(user_id: str, date_str: str) -> int:
    r = await get_redis()
    key = f"quota:{user_id}:{date_str}"
    val = await r.get(key)
    return int(val) if val else 0

async def increment_quota(user_id: str, date_str: str) -> int:
    r = await get_redis()
    key = f"quota:{user_id}:{date_str}"
    count = await r.incr(key)
    # expire at next midnight UTC (max 86400 seconds)
    await r.expire(key, 86400)
    return count

async def check_quota(user_id: str, date_str: str) -> tuple[int, bool]:
    """Returns (used, is_exceeded)"""
    used = await get_quota_used(user_id, date_str)
    return used, used >= FREE_DAILY_LIMIT
