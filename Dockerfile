FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --system --uid 10001 --home-dir /data gateboxlite \
    && mkdir /data && chown gateboxlite:gateboxlite /data && chmod 0700 /data
COPY app ./app
COPY migrations ./migrations
COPY web ./web
ENV GATEBOX_DATA_DIR=/data GATEBOX_COOKIE_SECURE=true PYTHONDONTWRITEBYTECODE=1
USER gateboxlite
# For external Docker deployments mount a private persistent volume at /data,
# then initialize the administrator via app.cli. Do not treat ephemeral data as durable.
EXPOSE 3000
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-3000} --no-access-log"]
