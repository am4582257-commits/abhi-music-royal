FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install --upgrade pip && pip install -r requirements.txt

COPY royal_bot.py abhi_royal_theme.png ./
RUN mkdir -p /app/music/youtube_cache

CMD ["python", "-u", "royal_bot.py"]
