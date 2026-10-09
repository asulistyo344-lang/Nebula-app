from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime
from uuid import UUID
from models import PlanType, DirectionType, SignalSourceType


# ── Auth ─────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: Optional[str] = None

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class GoogleAuthRequest(BaseModel):
    id_token: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserResponse"

class UserResponse(BaseModel):
    id: UUID
    email: str
    full_name: Optional[str]
    plan: PlanType

    class Config:
        from_attributes = True

TokenResponse.model_rebuild()


# ── FCM ──────────────────────────────────────────────────────────

class FCMTokenRequest(BaseModel):
    token: str
    device_id: Optional[str] = None


# ── Signals ──────────────────────────────────────────────────────

class SignalResponse(BaseModel):
    id: UUID
    pair: str
    direction: DirectionType
    entry: Optional[float]
    tp1: Optional[float]
    tp2: Optional[float]
    sl: Optional[float]
    rr: Optional[str]
    strength: int
    timeframe: str
    source: SignalSourceType
    regime: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True

class OnDemandRequest(BaseModel):
    pair: str
    timeframe: str = "15M"   # 15M | 1H | 4H


# ── Quota ────────────────────────────────────────────────────────

class QuotaResponse(BaseModel):
    used: int
    limit: int
    remaining: int
    is_pro: bool
    resets_at: str   # midnight UTC date string
