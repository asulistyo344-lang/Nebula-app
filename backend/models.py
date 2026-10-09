from sqlalchemy import (
    Column, String, Integer, Float, Boolean,
    DateTime, Enum, Text, ForeignKey, func
)
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
import uuid
import enum
from database import Base


class PlanType(str, enum.Enum):
    FREE = "free"
    PRO = "pro"


class DirectionType(str, enum.Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NO_SIGNAL = "NO_SIGNAL"


class SignalSourceType(str, enum.Enum):
    AUTO = "auto"
    ON_DEMAND = "on_demand"


class User(Base):
    __tablename__ = "users"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email         = Column(String(255), unique=True, nullable=False, index=True)
    full_name     = Column(String(255))
    hashed_password = Column(String(255))           # null for Google auth
    google_id     = Column(String(255), unique=True, nullable=True)
    plan          = Column(Enum(PlanType), default=PlanType.FREE, nullable=False)
    is_active     = Column(Boolean, default=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    updated_at    = Column(DateTime(timezone=True), onupdate=func.now())

    fcm_tokens    = relationship("FCMToken",   back_populates="user", cascade="all, delete")
    quota_logs    = relationship("QuotaLog",   back_populates="user", cascade="all, delete")


class FCMToken(Base):
    __tablename__ = "fcm_tokens"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id    = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    token      = Column(Text, nullable=False)
    device_id  = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User", back_populates="fcm_tokens")


class Signal(Base):
    __tablename__ = "signals"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pair        = Column(String(20), nullable=False, index=True)
    direction   = Column(Enum(DirectionType), nullable=False)
    entry       = Column(Float)
    tp1         = Column(Float)
    tp2         = Column(Float)
    sl          = Column(Float)
    rr          = Column(String(20))
    strength    = Column(Integer, default=0)
    timeframe   = Column(String(10), default="15M")
    source      = Column(Enum(SignalSourceType), default=SignalSourceType.AUTO)
    requested_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    # Condition snapshots (for audit / transparency)
    regime      = Column(String(10))   # BULL / BEAR
    trend_bull  = Column(Boolean)
    entry_bull  = Column(Boolean)
    atr_value   = Column(Float)


class QuotaLog(Base):
    __tablename__ = "quota_logs"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id    = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    signal_id  = Column(UUID(as_uuid=True), ForeignKey("signals.id"), nullable=True)
    date_utc   = Column(String(10), nullable=False)   # YYYY-MM-DD
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="quota_logs")
