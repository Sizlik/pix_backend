from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi_cache import FastAPICache
from starlette.middleware.cors import CORSMiddleware

from config import Settings, get_settings
from db.redis import get_redis_backend
from errors import IntegrationNotConfigured
from routes.bitrix import router as router_bitrix
from routes.bot import router as router_bot
from routes.chat import router as router_chat
from routes.notifications import router as router_notifications
from routes.orders import router as router_orders
from routes.organizations import router as router_organizations
from routes.payments import router as router_payment
from routes.users import router as router_users
from utils.celery_worker import change_states_on_moysklad


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        FastAPICache.init(get_redis_backend(), prefix="fastapi-cache")
        scheduler = None
        if settings.enable_scheduler:
            scheduler = AsyncIOScheduler()
            scheduler.add_job(change_states_on_moysklad, "interval", hours=1)
            scheduler.start()
            application.state.scheduler = scheduler

        try:
            yield
        finally:
            if scheduler is not None:
                scheduler.shutdown(wait=False)

    application = FastAPI(title="Pix Logistic API", lifespan=lifespan)
    api_router = APIRouter(prefix="/api_v1")

    api_router.include_router(router_users)
    api_router.include_router(router_bot)
    api_router.include_router(router_payment)
    api_router.include_router(router_bitrix)
    api_router.include_router(router_orders)
    api_router.include_router(router_chat)
    api_router.include_router(router_notifications)
    api_router.include_router(router_organizations)

    @api_router.get("/health", tags=["health"])
    async def health():
        return {"status": "ok"}

    @api_router.get("/")
    async def root():
        return {"message": "Hello World"}

    @api_router.get("/hello/{name}")
    async def say_hello(name: str):
        return {"message": f"Hello {name}"}

    @application.exception_handler(IntegrationNotConfigured)
    async def integration_not_configured_handler(
        request: Request,
        exc: IntegrationNotConfigured,
    ):
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    application.include_router(api_router)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    return application


app = create_app()
