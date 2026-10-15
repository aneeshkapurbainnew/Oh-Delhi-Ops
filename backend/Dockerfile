# Built from the repository root (see deploy/docker-compose.yml) so VERSION is included.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ .
COPY VERSION ./VERSION
RUN useradd --uid 1000 --create-home app && mkdir -p /data/uploads && chown -R app /app /data
USER app
EXPOSE 8000
# migrations run on every start; they are no-ops when the schema is current
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*' --workers 2"]
