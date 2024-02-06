#
FROM python:3.11

#
WORKDIR /code

#
COPY ./requirements.txt /code/requirements.txt

RUN pip install --upgrade pip
#
RUN pip install -r /code/requirements.txt

#
COPY . /code

#
CMD ["/bin/bash", "-c", "uvicorn main:app --host 0.0.0.0 --port 8000;celery -A manager.privoz_order.celery worker --loglevel=info -B;celery -A manager.privoz_order.celery flower --port 5555"]
