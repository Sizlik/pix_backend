from fastapi import FastAPI, APIRouter
from starlette.middleware.cors import CORSMiddleware

from routes.users import router as router_users
from routes.bitrix import router as router_bitrix
from routes.orders import router as router_orders
from routes.chat import router as router_chat


app = FastAPI()
router = APIRouter(prefix="/api_v1")

router.include_router(router)
router.include_router(router_users)
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


@router.get("/")
async def root():
    return {"message": "Hello World"}


@router.get("/hello/{name}")
async def say_hello(name: str):
    return {"message": f"Hello {name}"}
