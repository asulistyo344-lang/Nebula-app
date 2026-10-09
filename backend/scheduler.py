import asyncio
import logging
from datetime import datetime, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal
from models import Signal, User, FCMToken, QuotaLog, DirectionType, SignalSourceType, PlanType
from signal_engine import run_auto_scan, SignalResult
from redis_client import get_quota_used, increment_quota, FREE_DAILY_LIMIT
from fcm import send_signal_push

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler(timezone="UTC")


async def process_auto_signals():
    """
    Runs every hour:
    1. Scan all pairs
    2. Save signals to DB
    3. Push FCM to eligible users
    """
    logger.info(f"[Scheduler] Auto scan started at {datetime.now(timezone.utc).isoformat()}")

    try:
        results = await run_auto_scan()
    except Exception as e:
        logger.error(f"[Scheduler] Scan failed: {e}")
        return

    # Filter only real signals
    real_signals = [r for r in results if r.has_signal]
    logger.info(f"[Scheduler] {len(real_signals)} signals from {len(results)} pairs scanned")

    if not real_signals:
        logger.info("[Scheduler] No valid setups this hour")
        return

    async with AsyncSessionLocal() as db:
        saved_signals = []

        # Save signals to DB
        for result in real_signals:
            signal = Signal(
                pair=result.pair,
                direction=DirectionType(result.direction),
                entry=result.entry,
                tp1=result.tp1,
                tp2=result.tp2,
                sl=result.sl,
                rr=result.rr,
                strength=result.strength,
                timeframe=result.timeframe,
                source=SignalSourceType.AUTO,
                regime=result.regime,
                trend_bull=result.trend_bull,
                entry_bull=result.entry_bull,
                atr_value=result.atr_value,
            )
            db.add(signal)
            await db.flush()
            saved_signals.append((signal, result))

        await db.commit()
        logger.info(f"[Scheduler] {len(saved_signals)} signals saved to DB")

        # Get all active users
        users_result = await db.execute(
            select(User).where(User.is_active == True)
        )
        users = users_result.scalars().all()

        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        for signal, result in saved_signals:
            # Collect tokens per eligibility
            pro_tokens = []
            free_tokens = []

            for user in users:
                # Get user's FCM tokens
                tokens_result = await db.execute(
                    select(FCMToken).where(FCMToken.user_id == user.id)
                )
                tokens = [t.token for t in tokens_result.scalars().all()]
                if not tokens:
                    continue

                if user.plan == PlanType.PRO:
                    pro_tokens.extend(tokens)
                    # Log quota (unlimited for pro, just for records)
                    db.add(QuotaLog(
                        user_id=user.id,
                        signal_id=signal.id,
                        date_utc=date_str,
                    ))
                else:
                    # Check free quota
                    used = await get_quota_used(str(user.id), date_str)
                    if used < FREE_DAILY_LIMIT:
                        free_tokens.extend(tokens)
                        await increment_quota(str(user.id), date_str)
                        db.add(QuotaLog(
                            user_id=user.id,
                            signal_id=signal.id,
                            date_utc=date_str,
                        ))

            await db.commit()

            # Send push notifications
            all_tokens = pro_tokens + free_tokens
            if all_tokens:
                send_signal_push(
                    tokens=all_tokens,
                    pair=result.pair,
                    direction=result.direction,
                    entry=result.entry,
                    signal_id=str(signal.id),
                )

    logger.info("[Scheduler] Auto scan cycle complete")


def start_scheduler():
    # Run at the top of every hour
    scheduler.add_job(
        process_auto_signals,
        trigger=CronTrigger(minute=0),
        id="auto_signal_scan",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.start()
    logger.info("[Scheduler] Started — running hourly at :00")


def stop_scheduler():
    scheduler.shutdown(wait=False)
