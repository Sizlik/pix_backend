from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi_cache import FastAPICache
from starlette.middleware.cors import CORSMiddleware

from config import Settings, get_settings
from db.redis import get_redis_backend
from dependecies.chat import get_chat_realtime
from dependecies.notifications import get_notification_realtime
from dependecies.order_chat import get_order_chat_runtime
from errors import AddressNameConflict, AddressNotFound, IntegrationNotConfigured
from routes.addresses import router as router_addresses
from routes.bitrix import router as router_bitrix
from routes.bot import router as router_bot
from routes.chat import router as router_chat
from routes.link_preview import router as router_link_preview
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
        order_chat_runtime = None
        chat_realtime = get_chat_realtime()
        notification_realtime = get_notification_realtime()
        realtime_started = settings.app_env != "test"
        if realtime_started:
            await chat_realtime.start()
            await notification_realtime.start()
        if settings.enable_moysklad_order_chat:
            order_chat_runtime = get_order_chat_runtime(settings, chat_realtime)
            await order_chat_runtime.storage.ensure_bucket()
            await order_chat_runtime.worker.start()
            application.state.order_chat_runtime = order_chat_runtime
        if settings.enable_scheduler:
            scheduler = AsyncIOScheduler()
            scheduler.add_job(change_states_on_moysklad, "interval", hours=1)
            scheduler.start()
            application.state.scheduler = scheduler

        try:
            yield
        finally:
            if order_chat_runtime is not None:
                await order_chat_runtime.worker.stop()
            if realtime_started:
                await notification_realtime.stop()
                await chat_realtime.stop()
            if scheduler is not None:
                scheduler.shutdown(wait=False)

    application = FastAPI(title="Pix Logistic API", lifespan=lifespan)
    api_router = APIRouter(prefix="/api_v1")

    api_router.include_router(router_users)
    api_router.include_router(router_addresses)
    api_router.include_router(router_bot)
    api_router.include_router(router_payment)
    api_router.include_router(router_bitrix)
    api_router.include_router(router_orders)
    api_router.include_router(router_chat)
    api_router.include_router(router_link_preview)
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

    @application.exception_handler(AddressNotFound)
    async def address_not_found_handler(request: Request, exc: AddressNotFound):
        return JSONResponse(
            status_code=404,
            content={
                "detail": {
                    "code": "address_not_found",
                    "message": "Address not found",
                }
            },
        )

    @application.exception_handler(AddressNameConflict)
    async def address_name_conflict_handler(
        request: Request, exc: AddressNameConflict
    ):
        return JSONResponse(
            status_code=409,
            content={
                "detail": {
                    "code": "address_name_conflict",
                    "message": "Address name already exists",
                }
            },
        )

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
