# One image: the console (built) and the API. Used by Render and docker compose.
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npx vite build

FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1 PIP_BREAK_SYSTEM_PACKAGES=1
# Python 3.12, WeasyPrint libraries, ICU for Zawgyi conversion. Noto fonts ship in the app.
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.12 python3-pip python3-dev ca-certificates \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libharfbuzz-subset0 libffi8 \
        libicu-dev pkg-config build-essential \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app/backend
COPY backend/requirements.txt .
RUN python3.12 -m pip install --no-cache-dir -r requirements.txt
COPY backend/ .
COPY sample_data/ /app/sample_data/
COPY --from=web /web/dist /app/frontend/dist
CMD ["sh", "-c", "alembic upgrade head && exec python3.12 -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
