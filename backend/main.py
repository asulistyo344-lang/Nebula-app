import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from database import create_tables
from routes import router
from scheduler import start_scheduler, stop_scheduler
from fcm import init_firebase

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting Nebula API...")
    await create_tables()
    init_firebase()
    start_scheduler()
    logger.info("Nebula API ready")
    yield
    # Shutdown
    stop_scheduler()
    logger.info("Nebula API stopped")


app = FastAPI(
    title="Nebula Signal API",
    version="1.0.0",
    description="Precision crypto signals from the cosmos",
    lifespan=lifespan,
)

# CORS
origins = settings.ALLOWED_ORIGINS.split(",") if "," in settings.ALLOWED_ORIGINS else [settings.ALLOWED_ORIGINS]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.ENVIRONMENT == "development",
    )
