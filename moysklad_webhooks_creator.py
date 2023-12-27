import base64
import os

link = "https://api.moysklad.ru/api/remap/1.2/"
login = os.getenv("MOYSKLAD_LOGIN")
password = os.getenv("MOYSKLAD_PASWORD")
headers = {
    "Authorization": f'Basic {base64.b64encode(f"{login}:{password}".encode("UTF-8")).decode("utf-8")}'
}

