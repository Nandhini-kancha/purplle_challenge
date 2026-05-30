import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from app.database import init_db
from app import ingestion, metrics, funnel, anomalies, health

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

app = FastAPI(title="Store Intelligence API", lifespan=lifespan)

# Structured Logging Middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    # Just a placeholder for extracting request metadata
    response = await call_next(request)
    logger.info(f"trace_id=TODO store_id=TODO endpoint={request.url.path} status_code={response.status_code}")
    return response

# Graceful degradation via exception handler
@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}")
    # In a real app we would differentiate DB errors (503) from internal server errors (500)
    if "Connection refused" in str(exc) or "database" in str(exc).lower():
        return JSONResponse(
            status_code=503,
            content={"error": "Database unavailable", "details": "Service degraded"}
        )
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error"}
    )

app.include_router(ingestion.router)
app.include_router(metrics.router)
app.include_router(funnel.router)
app.include_router(anomalies.router)
app.include_router(health.router)
