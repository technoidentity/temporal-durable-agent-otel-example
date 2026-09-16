# Application image for the compose stack (profile: app). One image runs the
# worker, the ServiceNow/peer A2A agents, and the demo UI (different commands).
FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

# The package (hatchling) builds from app/ and needs README.md, so copy those
# before installing. config/ and scripts/ are runtime data, copied after.
COPY pyproject.toml README.md ./
COPY app ./app
RUN uv pip install --system --no-cache .

COPY config ./config
COPY scripts ./scripts

CMD ["python", "-m", "app.entrypoints.worker"]
