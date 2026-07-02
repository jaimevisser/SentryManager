FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    TESLACAM_ROOT=/data/TeslaCam

WORKDIR /app

COPY requirements.txt ./
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        ffmpeg \
        build-essential \
        zlib1g-dev \
        libjpeg62-turbo-dev \
        libopenjp2-7-dev \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--worker-class", "gthread", "--threads", "8", "--timeout", "120", "app.main:app"]
