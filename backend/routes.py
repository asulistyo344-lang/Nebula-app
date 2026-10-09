from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from datetime import datetime, timezone
from typing import Optional
import uuid

from database import get_db
from models import User, Signal, FCMToken, QuotaLog, PlanType, DirectionType, SignalSourceType
from auth import hash_password, verify_password, create_access_token, get_current_user
from schemas import (
    RegisterRequest, LoginRequest, TokenResponse, UserResponse,
    FCMTokenRequest, SignalResponse, OnDemandRequest, QuotaResponse,
)
from signal_engine import analyze_pair, TF_MAP, FREE_PAIRS, CRYPTO_PAIR_MAP
from redis_client import get_quota_used, increment_quota, check_quota, FREE_DAILY_LIMIT

router = APIRouter()

# ── Health ────────────────────────────────────────────────────────

@router.get("/health")
async def health():
    return {"status": "ok", "app": "Nebula"}

# ── Auth ─────────────────────────────────────────────────────────

@router.post("/auth/register", response_model=TokenResponse)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=body.email,
        full_name=body.full_name,
        hashed_password=hash_password(body.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token(str(user.id))
    return TokenResponse(access_token=token, user=UserResponse.model_validate(user))


@router.post("/auth/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if not user or not user.hashed_password:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account inactive")

    token = create_access_token(str(user.id))
    return TokenResponse(access_token=token, user=UserResponse.model_validate(user))


@router.get("/auth/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)):
    return UserResponse.model_validate(current_user)

# ── FCM Token ────────────────────────────────────────────────────

@router.post("/user/fcm-token", status_code=204)
async def register_fcm_token(
    body: FCMTokenRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Upsert by device_id if provided, else by token
    if body.device_id:
        result = await db.execute(
            select(FCMToken).where(
                FCMToken.user_id == current_user.id,
                FCMToken.device_id == body.device_id,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.token = body.token
            await db.commit()
            return

    # Check if token already registered
    result = await db.execute(
        select(FCMToken).where(FCMToken.token == body.token)
    )
    if result.scalar_one_or_none():
        return

    fcm = FCMToken(
        user_id=current_user.id,
        token=body.token,
        device_id=body.device_id,
    )
    db.add(fcm)
    await db.commit()

# ── Quota ────────────────────────────────────────────────────────

@router.get("/signals/quota", response_model=QuotaResponse)
async def get_quota(
    current_user: User = Depends(get_current_user),
):
    is_pro = current_user.plan == PlanType.PRO
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if is_pro:
        used_result = await get_quota_used(str(current_user.id), date_str)
        return QuotaResponse(
            used=used_result, limit=999999,
            remaining=999999, is_pro=True,
            resets_at=date_str,
        )

    used = await get_quota_used(str(current_user.id), date_str)
    remaining = max(0, FREE_DAILY_LIMIT - used)
    return QuotaResponse(
        used=used, limit=FREE_DAILY_LIMIT,
        remaining=remaining, is_pro=False,
        resets_at=date_str,
    )

# ── Signal Feed ───────────────────────────────────────────────────

@router.get("/signals/feed", response_model=list[SignalResponse])
async def get_feed(
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(Signal)
        .where(Signal.source == SignalSourceType.AUTO)
        .order_by(desc(Signal.created_at))
        .limit(limit)
    )
    result = await db.execute(query)
    signals = result.scalars().all()
    return [SignalResponse.model_validate(s) for s in signals]

# ── On Demand Signal ─────────────────────────────────────────────

@router.post("/signals/ondemand", response_model=SignalResponse)
async def on_demand_signal(
    body: OnDemandRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    is_pro = current_user.plan == PlanType.PRO
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Map display pair to internal symbol
    internal_pair = CRYPTO_PAIR_MAP.get(body.pair)
    if not internal_pair:
        # Try direct (e.g. BTCUSD)
        internal_pair = body.pair.upper().replace("/","").replace("-","")

    # Free tier: BTC only
    if not is_pro and internal_pair not in FREE_PAIRS:
        raise HTTPException(
            status_code=403,
            detail="Free plan: on-demand limited to BTC/USD. Upgrade to Pro for all pairs.",
        )

    # Quota check for free users
    if not is_pro:
        used, exceeded = await check_quota(str(current_user.id), date_str)
        if exceeded:
            raise HTTPException(
                status_code=429,
                detail=f"Daily quota reached ({FREE_DAILY_LIMIT}/day). Resets at midnight UTC.",
            )

    # Validate timeframe
    if body.timeframe not in TF_MAP:
        raise HTTPException(status_code=400, detail="Invalid timeframe. Use 15M, 1H, or 4H.")

    # Run analysis
    try:
        result = await analyze_pair(internal_pair, body.timeframe)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Market data unavailable: {str(e)}")

    # Save signal
    direction = DirectionType(result.direction)
    signal = Signal(
        pair=result.pair,
        direction=direction,
        entry=result.entry,
        tp1=result.tp1,
        tp2=result.tp2,
        sl=result.sl,
        rr=result.rr,
        strength=result.strength,
        timeframe=result.timeframe,
        source=SignalSourceType.ON_DEMAND,
        requested_by=current_user.id,
        regime=result.regime,
        trend_bull=result.trend_bull,
        entry_bull=result.entry_bull,
        atr_value=result.atr_value,
    )
    db.add(signal)
    await db.flush()

    # Deduct quota for free users
    if not is_pro:
        await increment_quota(str(current_user.id), date_str)
        db.add(QuotaLog(
            user_id=current_user.id,
            signal_id=signal.id,
            date_utc=date_str,
        ))

    await db.commit()
    await db.refresh(signal)
    return SignalResponse.model_validate(signal)

# ── Signal History ────────────────────────────────────────────────

@router.get("/signals/history", response_model=list[SignalResponse])
async def get_history(
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Returns signals relevant to this user (auto + their on-demand)"""
    query = (
        select(Signal)
        .where(
            (Signal.source == SignalSourceType.AUTO) |
            (Signal.requested_by == current_user.id)
        )
        .order_by(desc(Signal.created_at))
        .limit(limit)
    )
    result = await db.execute(query)
    signals = result.scalars().all()
    return [SignalResponse.model_validate(s) for s in signals]
