FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    APP_ENV=development \
    TESLACAM_ROOT=/data/TeslaCam

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY config ./config

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--worker-class", "gthread", "--threads", "8", "--timeout", "120", "app.main:app"]
