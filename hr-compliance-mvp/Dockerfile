# syntax=docker/dockerfile:1

FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV FLASK_SECRET_KEY=dev
EXPOSE 8000

CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8000"]

