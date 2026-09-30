import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.routers import auth, ledger, markets, stream
from app.sweeper import sweep_loop


@asynccontextmanager
async def lifespan(_app: FastAPI):
    task = None
    if settings.market_sweep_interval_s > 0:
        task = asyncio.create_task(sweep_loop(), name="market-close-sweeper")
    yield
    if task is not None:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="Meridian API", version="1.0.0", lifespan=lifespan)

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


@app.exception_handler(HTTPException)
async def http_error(_request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})


@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, _exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"error": "Invalid request."})
