"""FastAPI 应用入口。"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.routes import router
from .core.config import SERVICE_HOST, SERVICE_PORT
from .core.db import init_db


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="Multi-agent", version="0.1.0", lifespan=lifespan)

# 本地 WebView 前端跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ValueError)
async def value_error_handler(_: Request, exc: ValueError) -> JSONResponse:
    """业务错误（会话不存在 / 未设主理人等）统一返回 400。"""
    return JSONResponse(status_code=400, content={"detail": str(exc)})


app.include_router(router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "service": "multi-agent"}


def main() -> None:
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=SERVICE_HOST,
        port=SERVICE_PORT,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
