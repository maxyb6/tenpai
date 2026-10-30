FROM python:3.12-slim

# WeasyPrint system libraries and fonts for Burmese and Khmer PDFs.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libffi8 libicu-dev pkg-config build-essential \
        fonts-noto-core fonts-noto-ui-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ .
COPY sample_data/ /app/sample_data/

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
