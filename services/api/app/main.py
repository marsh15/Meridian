from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.fanout import tick_hub
from app.redis import close_redis
from app.routers import auth, intel, ledger, markets, stream, users
from app.telemetry import setup_telemetry


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # one pg LISTEN → Redis PUBLISH bridge per process; SSE clients
    # subscribe to Redis instead of holding Postgres connections (ADR 0009)
    await tick_hub.start()
    yield
    await tick_hub.stop()
    await close_redis()


app = FastAPI(title="Meridian API", version="1.0.0", lifespan=lifespan)

setup_telemetry(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in settings.cors_origins.split(",") if o],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(markets.router)
app.include_router(stream.router)
app.include_router(ledger.router)
app.include_router(users.router)
app.include_router(intel.router)


@app.exception_handler(HTTPException)
async def http_error(_request: Request, exc: HTTPException) -> JSONResponse:
    # exc.headers carries things like Retry-After on 429s
    return JSONResponse(
        status_code=exc.status_code, content={"error": exc.detail}, headers=exc.headers
    )


@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, _exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"error": "Invalid request."})
