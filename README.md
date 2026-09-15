# Temporal + LangGraph + OpenTelemetry reference application

A small, production-shaped Python service that runs a LangGraph agent inside a
Temporal workflow, fully observable through OpenTelemetry, and driven entirely by
configuration. It works against a self-hosted Temporal server or Temporal Cloud
with only config changes.

The agent exposes one tool, `current_time`, so the end-to-end path is easy to
follow:

```
User request
  -> Temporal Workflow
    -> LangGraph agent (LLM)   [activity]
      -> LLM decides to call a tool
        -> current_time tool   [activity]
      -> LangGraph agent (LLM) [activity]
    -> final response
```

## Architecture

```
                         User
                          |
                          v
                    Temporal Client            (python -m app.entrypoints.workflow)
                          |
                          v
                   Temporal Server
                          |
                          v
                   Agent Workflow              (deterministic; no clock/env/IO)
                          |
                          v
                       LangGraph
                          |
             +------------+-------------+
             |                          |
             v                          v
       Agent Activity              Tool Activity
             |                          |
             v                          v
            LLM                    current_time


                  Observability
------------------------------------------------

Worker
 |
 +-- Temporal traces (TracingInterceptor)
 +-- Temporal SDK worker metrics (runtime OTLP exporter)
 +-- LangGraph / agent traces
 +-- custom agent metrics
 |
 v
OTel Collector
 |
 +------> Prometheus ------> Grafana
 |
 +------> trace backend (debug by default; Tempo-ready)


Temporal Cloud (optional, separate source)
 |
 | OpenMetrics (scraped by the collector)
 v
OTel Collector ------> Prometheus ------> Grafana
```

The stack keeps three telemetry sources distinct and lets them converge in the
same backend:

1. **Application metrics** — `agent.*` counters/histograms from the worker.
2. **Temporal SDK / worker metrics** — emitted by the Temporal core SDK.
3. **Temporal Cloud service metrics** — scraped by the collector, never by the
   worker.

## Project layout

```
app/
  config/         one typed settings model + layered loader
  temporal/       unified client, runtime (SDK metrics), retry policy
  agent/          LangGraph graph, nodes, tools, state
  workflows/      the AgentWorkflow
  observability/  OTel traces/metrics, structured logging
  infrastructure/ health checks + docker compose lifecycle
  entrypoints/    worker, workflow, infrastructure
config/           config.yaml + config.example.yaml
docker/           otel-collector.yaml, prometheus.yml, grafana/, worker.Dockerfile
docker-compose.yml
```

## Configuration

Everything is configuration-driven. Precedence, highest first:

```
environment variables  >  config YAML  >  safe defaults
```

- `config/config.yaml` is the base document. It never contains secrets; use
  `${VAR}` to pull them from the environment (e.g. `api_key: ${OPENAI_API_KEY}`).
- Documented environment variables override any nested value (see
  `.env.example` and `app/config/loader.py`).
- One root model, `AppSettings`, is validated on load. Invalid combinations fail
  fast (e.g. `temporal.mode=cloud` without cloud credentials).

## Quick start (self-hosted, local)

Prerequisites: Docker, Python 3.12+, and [uv](https://docs.astral.sh/uv/).

```bash
make install                       # create .venv and install deps
cp .env.example .env               # optional; defaults already work with LLM_PROVIDER=fake
cp config/config.example.yaml config/config.yaml

make infra-up                      # start Temporal, OTel Collector, Prometheus, Grafana
make worker                        # start the worker (leave running)
make run MESSAGE="What time is it?" # in another shell
```

Expected output:

```
Workflow ID: hello-agent-...
Result: The current UTC time is 2026-...T...+00:00.
```

`LLM_PROVIDER=fake` (the default) runs the complete workflow -> agent -> tool ->
agent path offline, with no API key. Set `LLM_PROVIDER=openai` and
`OPENAI_API_KEY=...` to use a real model.

### Access

| Service          | URL                     |
|------------------|-------------------------|
| Temporal gRPC    | `localhost:7233`        |
| Temporal UI      | http://localhost:8233   |
| OTLP gRPC / HTTP | `localhost:4317` / `4318` |
| Collector /metrics | http://localhost:8889/metrics |
| Prometheus       | http://localhost:9090   |
| Grafana          | http://localhost:3000 (anonymous admin) |

Grafana auto-provisions the Prometheus datasource and the **Temporal LangGraph
Agent** dashboard — no manual UI setup.

## Switching to Temporal Cloud (config only)

No application code changes. Set the mode and cloud credentials:

```bash
export TEMPORAL_MODE=cloud
export TEMPORAL_CLOUD_ADDRESS=my-namespace.acct.tmprl.cloud:7233
export TEMPORAL_CLOUD_NAMESPACE=my-namespace.acct
export TEMPORAL_CLOUD_API_KEY=...          # API-key auth; TLS is enabled automatically
```

or in `config/config.yaml`:

```yaml
temporal:
  mode: cloud
  cloud:
    address: my-namespace.acct.tmprl.cloud:7233
    namespace: my-namespace.acct
    api_key: ${TEMPORAL_CLOUD_API_KEY}
    tls_enabled: true
```

The same `create_temporal_client` handles both modes; only the resolved
address/namespace/TLS/API-key differ.

### Temporal Cloud service metrics

These are a separate source and are **scraped by the collector**, never by the
worker. Enable the `prometheus/temporal_cloud` receiver in
`docker/otel-collector.yaml` (add it to the `metrics` pipeline) and provide the
token:

```bash
export TEMPORAL_METRICS_API_KEY=...        # collector reads it via ${env:...}
```

Set `observability.temporal_cloud_metrics.enabled: true` in config to record the
intent (validation requires the token). When disabled, the Grafana Cloud panels
simply show no data.

## How telemetry flows

- **Traces**: `TracingInterceptor` (Temporal OpenTelemetry) is attached to both
  the client and the worker. The client entrypoint initializes OTel too, so a
  single distributed trace links client -> workflow -> agent activity ->
  tool activity. Spans go over OTLP to the collector.
- **Application metrics**: `app/observability/metrics.py` records `agent.llm.*`,
  `agent.tool.*`, `agent.workflow.*` through the OTel SDK, exported over OTLP.
  Labels are low-cardinality only (`model`, `tool.name`, `status`) — never
  workflow ids, prompts or user ids.
- **Temporal SDK worker metrics**: emitted by the Temporal core SDK via the
  runtime's OTLP exporter, straight to the collector.
- **Collector -> Prometheus -> Grafana**: the collector exposes a Prometheus
  endpoint on `:8889`; Prometheus scrapes it (OTLP -> Collector -> Prometheus,
  not a direct scrape of the worker); Grafana reads Prometheus.

## Running infrastructure independently

The worker never stops infrastructure. Manage it on its own:

```bash
make infra-up        # docker compose up -d + wait for health
make infra-status    # health of each service
make infra-down      # docker compose down
```

With `infrastructure.auto_start: true`, the worker starts Compose only if the
required services are not already reachable (it never duplicates containers).
With `auto_start: false`, the worker runs no Docker commands and fails clearly if
a required service is unavailable.

## Notes on the current Temporal SDK (vs. common older examples)

Built and verified against `temporalio==1.33.0`. A few things differ from stale
samples; each is intentional:

- **Worker SDK metrics use `TelemetryConfig(metrics=OpenTelemetryConfig(...))`**,
  not a `MetricBuffer -> MetricsExporter -> MeterProvider` chain. `MetricBuffer`
  is for in-process consumption; the runtime's native OTLP exporter is the
  supported way to ship SDK metrics to a collector.
  - `attach_service_name=False` is set on purpose: the collector adds
    `service_name` from the OTLP resource, and letting the SDK add it too makes
    the Prometheus exporter reject metrics ("duplicate label names").
- **LangGraph nodes must be module-level functions.** The plugin identifies
  nodes by qualified name, so closures are rejected. The model is injected via a
  small `configure_agent()` call at graph-build time.
- **The tool router is `async`.** LangGraph offloads sync conditional-edge
  functions with `run_in_executor`, which Temporal's workflow event loop does not
  implement; an async router is awaited directly.
- **Node state is normalized with `convert_to_messages`.** Graph state crosses
  the activity boundary as plain dicts, so nodes rebuild proper
  `AIMessage`/`ToolMessage` objects before use. A custom `tools_node` replaces
  `ToolNode` for the same reason (its strict `isinstance` check rejects dicts).

## Make targets

```
make install       make infra-up     make infra-status   make run MESSAGE="..."
make worker        make infra-down   make logs           make test
```

## Troubleshooting

- **`temporal.mode=cloud requires ...`** — cloud mode needs address, namespace
  and API key. Set them via env or `config/config.yaml`.
- **Worker exits with "required services unavailable and auto_start=false"** —
  start infrastructure (`make infra-up`) or set `infrastructure.auto_start: true`.
- **No `temporal_*` metrics in Prometheus** — check the collector logs for
  "duplicate label names"; ensure only one worker is running and the collector
  is reachable at the configured OTLP endpoint.
- **`agent_*` metrics slow to appear** — the app meter exports on an interval
  (15s); Temporal SDK metrics use ~10s.
- **Docker not available** — infrastructure commands fail with a clear error;
  run against already-running services with `auto_start: false`.

## Tests

```bash
make test
```

Unit tests cover config parsing and env overrides, Temporal mode selection and
cloud/self-hosted validation, LangGraph construction, the `current_time` tool,
metric recording, and infrastructure health checks. They mock Docker/OTLP and
require no external services.
