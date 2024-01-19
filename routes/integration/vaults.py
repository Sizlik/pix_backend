from typing import Optional

import asyncio
import requests
from fastapi import APIRouter
from bs4 import BeautifulSoup
from fastapi_cache import FastAPICache
from fastapi_cache.decorator import cache
from fastapi import Request, Response
import zipfile
import pandas as pd

router = APIRouter(tags=["vaults"], prefix="/vaults")


def vault_key_builder(
        func,
        namespace: Optional[str] = "",
        request: Request = None,
        response: Response = None,
        *args,
        **kwargs,
):
    prefix = FastAPICache.get_prefix()
    cache_key = f"{prefix}:vaults"
    return cache_key


@router.get("/")
@cache(expire=60, key_builder=vault_key_builder)
async def get_vaults():
    # sberbank 42
    # alphabank 52
    # tinkoff 105
    # sberbank = BeautifulSoup(requests.get("https://www.bestchange.ru/sberbank-to-tether-trc20.html").text, "html.parser")
    # await asyncio.sleep(3)
    # alphabank = BeautifulSoup(requests.get("https://www.bestchange.ru/alfaclick-to-tether-trc20.html").text, "html.parser")
    # await asyncio.sleep(3)
    # tinkoff = BeautifulSoup(requests.get("https://www.bestchange.ru/tinkoff-to-tether-trc20.html").text, "html.parser")
    # # vtb = BeautifulSoup(requests.get("https://www.bestchange.ru/vtb-to-tether-trc20.html").text, "html.parser")
    #
    # sberbank_price = 0
    # for i in sberbank.find_all('div', class_="fs", limit=3):
    #     sberbank_price += float(i.text.split(" ")[0])
    # sberbank_price = round(sberbank_price/3, 2)
    #
    # alphabank_price = 0
    # for i in alphabank.find_all('div', class_="fs", limit=3):
    #     alphabank_price += float(i.text.split(" ")[0])
    # alphabank_price = round(alphabank_price / 3, 2)
    #
    # tinkoff_price = 0
    # for i in tinkoff.find_all('div', class_="fs", limit=3):
    #     tinkoff_price += float(i.text.split(" ")[0])
    # tinkoff_price = round(tinkoff_price / 3, 2)

    with open("./downloaded/vaults.zip", "wb") as file:
        file.write(requests.get("http://api.bestchange.ru/info.zip").content)

    with zipfile.ZipFile("./downloaded/vaults.zip", "r") as zip_file:
        zip_file.extractall("./downloaded/vaults")

    data_frame = pd.read_csv("./downloaded/vaults/bm_rates.dat", header=None, sep=";")

    sberbank = data_frame[(data_frame[0] == 42) & (data_frame[1] == 10)].sort_values(by=3)
    sberbank_price = round(sberbank.iloc[:3][3].mean(), 2)

    alphabank = data_frame[(data_frame[0] == 52) & (data_frame[1] == 10)].sort_values(by=3)
    alphabank_price = round(alphabank.iloc[:3][3].mean(), 2)

    tinkoff = data_frame[(data_frame[0] == 105) & (data_frame[1] == 10)].sort_values(by=3)
    tinkoff_price = round(tinkoff.iloc[:3][3].mean(), 2)

    # vtb_price = 0
    # for i in vtb.find_all('div', class_="fs", limit=3):
    #     vtb_price += float(i.text.split(" ")[0])
    # vtb_price = round(vtb_price / 3, 2)
    # return data_frame
    # return {"sberbank": sberbank_price, "alphabank": alphabank_price, "tinkoff": tinkoff_price, "vtb": vtb_price}
    return {"sberbank": sberbank_price, "alphabank": alphabank_price, "tinkoff": tinkoff_price}

