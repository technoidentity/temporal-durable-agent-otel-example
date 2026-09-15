# Optional image to run the worker inside the Compose stack (profile: app).
FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml ./
RUN uv pip install --system --no-cache .

COPY app ./app
COPY config ./config

CMD ["python", "-m", "app.entrypoints.worker"]
