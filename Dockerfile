FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PILGAN_DATA_DIR=/var/data \
    PORT=8000

WORKDIR /app

# Library sistem yang dibutuhkan OpenCV headless.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-prod.txt .
RUN pip install --no-cache-dir -r requirements-prod.txt

COPY . .

# Dibuat ulang oleh aplikasi saat start, tetapi membantu saat build lokal.
RUN mkdir -p /var/data/uploads /var/data/instance

EXPOSE 8000

CMD ["gunicorn", "-c", "gunicorn.conf.py", "app:app"]
