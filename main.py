from fastapi import FastAPI, APIRouter
from fastapi_cache import FastAPICache
from starlette.middleware.cors import CORSMiddleware

from db.redis import get_redis_backend
from manager.privoz_order import celery
from routes.users import router as router_users
from routes.bot import router as router_bot
from routes.bitrix import router as router_bitrix
from routes.payments import router as router_payment
from routes.orders import router as router_orders
from routes.chat import router as router_chat


app = FastAPI()
router = APIRouter(prefix="/api_v1")

router.include_router(router)
router.include_router(router_users)
router.include_router(router_bot)
router.include_router(router_payment)
router.include_router(router_bitrix)
router.include_router(router_orders)
router.include_router(router_chat)

app.include_router(router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    celery.worker_main(["-A", "manager.privoz_order.celery", "worker", "--loglevel=info", "-B"])
    FastAPICache.init(get_redis_backend(), prefix="fastapi-cache")


def test():
    print(123)


@router.get("/")
async def root():
    return {"message": "Hello World"}


@router.get("/hello/{name}")
async def say_hello(name: str):
    return {"message": f"Hello {name}"}
