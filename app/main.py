from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize DB schema
    await init_db()
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Customer Support & Operations AI Agent with Human-in-the-Loop Approval",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["Health"])
async def health_check():
    """Health status endpoint."""
    return {
        "status": "healthy",
        "app": settings.app_name,
        "environment": settings.environment,
    }
