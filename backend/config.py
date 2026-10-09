from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    DATABASE_URL: str
    REDIS_URL: str = "redis://localhost:6379"
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 10080  # 7 days
    FIREBASE_CREDENTIALS_PATH: str = "./firebase-credentials.json"
    CRYPTO_API_BASE: str = "https://api.crypto.com/exchange/v1/public"
    APP_NAME: str = "Nebula"
    ENVIRONMENT: str = "development"
    ALLOWED_ORIGINS: str = "*"

    class Config:
        env_file = ".env"

settings = Settings()
