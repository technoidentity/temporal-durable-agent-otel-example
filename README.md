<div align="center">

# 🥤 PepsiCo Agent Ops

**Durable, observable, multi‑agent orchestration — a config‑driven reference platform.**

[![Python 3.12+](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Temporal](https://img.shields.io/badge/Temporal-durable%20execution-000000)](https://temporal.io/)
[![LangGraph](https://img.shields.io/badge/LangGraph-agent%20reasoning-1C7D73)](https://langchain-ai.github.io/langgraph/)
[![OpenTelemetry](https://img.shields.io/badge/OpenTelemetry-traces%20%26%20metrics-425CC7?logo=opentelemetry&logoColor=white)](https://opentelemetry.io/)
[![Arize](https://img.shields.io/badge/Arize-LLM%20observability-6D28D9)](https://arize.com/)
![Tests](https://img.shields.io/badge/tests-77%20passing-2EA043)

`Multi‑agent` · `Human‑in‑the‑loop` · `Agent‑to‑agent` · `Third‑party (ServiceNow)` · `Chaos testing` · `Config‑driven`

</div>

> **LangGraph owns agent reasoning · Temporal owns durable execution · Lyzr routes the models.**

A runnable reference implementation of an **enterprise agent platform**: multiple AI agents that
collaborate on a business task, run **durably** on Temporal, pause for **human approval** when
needed, call **other agents** (including a **third‑party ServiceNow agent**), and are **fully
observable**. Everything is **config‑driven**, and a compact **demo UI** lets you drive and
stress‑test it.

## Contents

|  |  |  |
|---|---|---|
| [1. What it does](#1-what-it-does-the-business-story) | [2. Quick start](#2-see-it-in-5-minutes) | [3. Architecture](#3-architecture) |
| [4. Capabilities](#4-capabilities-whats-built) | [5. Demo UI](#5-the-demo-ui-for-business-users) | [6. CLI usage](#6-running-from-the-cli-for-developers) |
| [7. Configuration](#7-configuration) | [8. Temporal Cloud](#8-temporal-cloud-config-only) | [9. Observability](#9-observability) |
| [10. Project layout](#10-project-layout) | [11. Testing](#11-testing) | [12. Glossary](#12-glossary-for-non-specialists) |
| [13. SDK notes](#13-notes-on-the-current-temporal-sdk-vs-older-examples) | [14. Troubleshooting](#14-troubleshooting) | [15. Agent Studio](#15-agent-studio-guided-multi-agent-demo) |

---

## 1. What it does (the business story)

A PepsiCo distributor places a bulk order (e.g. *"Star Distributors: 500 cases
of Pepsi 330ml at 20% discount"*). A team of specialist agents handles it:

```
Distributor request
        │
        ▼
   Intake  ──►  Inventory  ──►  Pricing  ──►  Fulfillment  ──►  Account  ──►  Supervisor
   (parse)      (stock)        (promo/        (plan +           (context)     (final
                               approval?)     risk?)                          decision)
        │
        ├─ discount over threshold?  ──►  HUMAN APPROVAL (workflow pauses, durably)
        │
        └─ fulfillment risk?         ──►  ServiceNow agent opens an INCIDENT (agent‑to‑agent)
```

Every step is a real LLM agent call (via **Lyzr**), every step is **durable**
(survives crashes/retries via **Temporal**), and every step is **traced and
measured** (via **OpenTelemetry → Arize / Grafana**).

**Why it matters:** teams get identity, durability, human‑in‑the‑loop, secure
tool/API access, and observability *for free* from the platform, and focus only
on agent behavior.

---

## 2. See it in 5 minutes

Two ways to run it. **Offline mode** needs no keys; **live mode** uses real Lyzr agents.

### Prerequisites
- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- A running Temporal server (self‑hosted `localhost:7233`, or Temporal Cloud — see §8)
- (Optional) Docker, for the bundled Prometheus/Grafana/OTel stack

### Setup
```bash
make install                                   # create .venv, install deps
cp .env.example .env                           # local settings (gitignored)
cp config/config.example.yaml config/config.yaml
```

### Option A — Offline demo (no keys)
Uses a deterministic `fake` model so the whole flow runs without any API key.
```bash
# terminal 1 — worker (single hello-agent + tool)
LLM_PROVIDER=fake make worker
# terminal 2
make run MESSAGE="What time is it?"
# -> Result: The current UTC time is 2026-...T...+00:00
```

### Option B — Live multi‑agent demo (Lyzr)
1. Put your Lyzr key in `.env`: `LYZR_API_KEY=sk-...`
2. Provision the agent roster (idempotent — safe to re‑run):
   ```bash
   python scripts/lyzr_provision.py            # creates the PepsiCo agents in Lyzr
   ```
3. Start the worker with the multi‑agent pipeline enabled and open the UI:
   ```bash
   LLM_PROVIDER=lyzr MULTI_AGENT_ENABLED=true make worker   # or set multi_agent.enabled in config
   make ui                                                   # http://localhost:8000
   ```
4. In the **demo UI**, type an order, pick a scenario, and hit **Run order**.

> The UI is the easiest way to experience everything — see §5.

---

## 3. Architecture

```
                          USER  (Demo UI  ·  CLI)
                                   │
                                   ▼
                            Temporal Client
                                   │  start / signal / query
                                   ▼
                            Temporal Server ────────────────┐  durable state,
                                   │                         │  retries, timers,
                                   ▼                         │  HITL waits
                          Order Workflow  (deterministic)    │
                                   │                         │
                     ┌─────────────┼───────────────┐         │
                     ▼             ▼               ▼         │
              LangGraph pipeline   HITL gate    A2AWorkflow
              (agents as           (waits for   (orchestration-
               activities)          a human)     level A2A)
                     │
        each agent's reasoning ──► LYZR (model router) ──► LLM
                     │
                     ▼
   Intake → Inventory → Pricing → Fulfillment ──A2A on risk──► ServiceNow agent → incident
                                        │
                                   Account → Supervisor

  OBSERVABILITY
  ─────────────────────────────────────────────────────────────────────
  Worker / Client
    ├─ Temporal traces (TracingInterceptor)
    ├─ Temporal SDK worker metrics (workflow/activity/retries/slots)
    ├─ agent + LLM spans (OpenInference)
    └─ custom metrics (agent.llm.*, agent.tool.*, agent.hitl.*, agent.chaos.*)
                    │
                    ├───────────────►  Arize Cloud   (LLM/agent traces + evals)
                    │
                    └──► OTel Collector ──► Prometheus ──► Grafana (dashboards)
```

**Three telemetry sources stay distinct and converge in the backend:**
1. Application metrics (`agent.*`) 2. Temporal SDK worker metrics 3. Temporal
Cloud service metrics (scraped by the collector, optional).

---

## 4. Capabilities (what's built)

| Capability | What it gives you | Where |
|---|---|---|
| **Multi‑agent pipeline** | 6 specialist agents collaborate on an order, durably | `app/agent/multi.py`, `OrderWorkflow` |
| **Human‑in‑the‑loop** | Workflow pauses for approval when discount > threshold; resume by signal | `app/workflows/*`, `app/platform/hitl.py` |
| **Agent‑to‑agent (A2A)** | Thin A2A protocol (agent card + task endpoint). An **agent can call another agent from inside its own node**, and workflows can orchestrate A2A too | `app/platform/a2a.py`, `app/agent/multi.py` |
| **Third‑party agent** | ServiceNow incident agent (simulator now, real PDI by config); the fulfillment agent reaches it over A2A on risk | `app/integrations/servicenow.py` |
| **Chaos / fault injection** | Inject transient/permanent errors, latency/timeouts, forced approval | `app/platform/chaos.py` |
| **Model router (Lyzr)** | Each agent's reasoning routed through Lyzr; model chosen on Lyzr's side | `app/agent/lyzr.py` |
| **Observability** | Arize Cloud + Prometheus/Grafana + Temporal UI; traces, metrics, logs | `app/observability/*` |
| **Config‑driven** | One typed settings model; env > YAML > defaults; add a key → real service | `app/config/*` |
| **Demo UI** | Start/mix/inject/approve — all from one compact page | `app/ui/*` |

Everything is **selectable by config** and **overridable per run** (so the UI can change behavior live).

### Agent‑to‑agent (A2A), in detail

A2A is a **capability of the agents**, not only the orchestrator. There are two
complementary patterns, and both are supported:

1. **Agent‑level A2A (an agent calls another agent).** A LangGraph node can call
   a remote agent from *inside itself*. Concretely, the **fulfillment agent**
   detects a fulfillment risk and calls the **ServiceNow agent** over A2A to open
   an incident — this happens within the node. Because every node runs inside a
   Temporal **Activity**, the A2A HTTP call is durable at node granularity (its
   result is recorded and the node is retried on failure), with no determinism
   concern. See `_agent_dispatch_servicenow` in `app/agent/multi.py`.
2. **Orchestration‑level A2A (a workflow calls an agent).** The standalone
   `A2AWorkflow` makes an A2A call as a first‑class durable workflow (via the
   `a2a` entrypoint) — useful when the interaction *is* the process, or to
   compose agents outside a single graph.

Any A2A agent (ours or a third party) exposes the same contract — an **agent
card** (`GET /.well-known/agent-card.json`) and a **task endpoint**
(`POST /a2a/message`) — so new agents plug in uniformly. Remote agents are
registered in config under `a2a.agents` (name → URL); the ServiceNow target the
fulfillment agent uses comes from `third_party.servicenow.a2a_url`. Giving
another agent an A2A capability is the same pattern: resolve a target URL from
config and call `A2AClient` inside that agent's node.

---

## 5. The demo UI (for business users)

`make ui` → **http://localhost:8000** (PepsiCo‑themed, compact).

**Left panel — build a run:**
- **Distributor request** — free text, or click a preset.
- **Approval (HITL):** set the **discount threshold %**, choose gate **mode**,
  or **disable**/**force** the approval gate.
- **Chaos:** pick a **target agent**, a **fault** (transient / permanent /
  latency), **attempts**, and **latency seconds**.
- **Run order.**

**Right panel — watch it happen:**
- Each run shows a live **status pill** (RUNNING → PENDING → COMPLETED).
- If approval is required, an **Approve / Reject** control appears — click to
  resume the paused workflow.
- When done, you see each **agent's output**, the **approval outcome**, and any
  **ServiceNow incident** opened.

**Top bar links:** Temporal UI, Grafana, Prometheus, Arize/Phoenix.

### Try these scenarios in the UI
| Goal | How |
|---|---|
| Normal fast order | Request with **10%** discount → auto‑approved |
| Trigger human approval | Request with **20%** discount (or click **Force approval**) → Approve/Reject |
| See durability/retries | Chaos: target `inventory`, mode `transient_error`, attempts `1` → it fails once, Temporal retries, order still completes |
| See a failure | Chaos: mode `permanent_error` → activity exhausts retries, run shows FAILED |
| Open a ServiceNow incident | Request a **rush order with likely shortfall** → fulfillment flags risk → incident opened |

---

## 6. Running from the CLI (for developers)

```bash
# Worker (hosts workflows + agents). Enable pieces via config or env:
LLM_PROVIDER=lyzr MULTI_AGENT_ENABLED=true make worker

# Hello single-agent workflow
make run MESSAGE="What time is it?"

# Multi-agent order (add flags to mix scenarios)
make order REQUEST="Star Distributors: 500 cases Pepsi at 20% discount"
python -m app.entrypoints.order -r "..." --threshold 10 --force-hitl \
       --chaos-target pricing --chaos-mode latency --chaos-latency 5

# Approve / reject a paused order (id printed when it pauses)
python -m app.entrypoints.approve --workflow-id <id> --approve --note "ok"
python -m app.entrypoints.approve --workflow-id <id> --status

# Third-party ServiceNow agent (simulator) + a peer A2A agent
python -m app.entrypoints.servicenow_agent --port 8801
python -m app.entrypoints.a2a_server --name peer --port 8802 --handler lyzr --lyzr-agent-id <id>

# Call an agent over A2A, durably
python -m app.entrypoints.a2a --agent servicenow --message "open incident: ..."

# Interactive start/stop/status of infra + worker
make services
```

`scripts/services.sh` detects each dependency whether it runs in Docker or
natively (port/HTTP probes) and reports the Docker container when present.

---

## 7. Configuration

**One typed model** (`app/config/models.py`), loaded with precedence:

```
environment variables   >   config/config.yaml   >   safe defaults
```

- `config/config.yaml` is the base document — **no secrets**; use `${VAR}` to
  pull them from the environment.
- Secrets live in **`.env`** (gitignored): `LYZR_API_KEY`, `ARIZE_API_KEY`,
  `SERVICENOW_*`, etc.
- Invalid combinations **fail fast** (e.g. `temporal.mode=cloud` without creds).

Key sections (see `config/config.example.yaml` for the full annotated file):

| Section | Purpose |
|---|---|
| `temporal` | self‑hosted vs Cloud, task queue, timeouts, retry policy |
| `llm` | provider (`lyzr` / `openai` / `ollama` / `fake`), model, keys |
| `multi_agent` | enable the pipeline, agent order, Lyzr agent map |
| `hitl` | approval threshold, mode, timeout, timeout policy |
| `a2a` | remote agent registry, call timeout |
| `third_party.servicenow` | simulator vs real PDI, risk keywords |
| `chaos` | fault target/mode/attempts/latency/force_hitl |
| `observability` | OTel endpoint, Arize, Phoenix, metrics/traces toggles |
| `infrastructure` | docker‑compose auto‑start + health checks |
| `ui` | demo UI host/port |

**Add a real key in config/`.env` and the mock becomes the real service** — no
code change (Lyzr, Arize, ServiceNow PDI, Temporal Cloud).

---

## 8. Temporal Cloud (config only)

No code changes — set the mode and credentials:

```bash
export TEMPORAL_MODE=cloud
export TEMPORAL_CLOUD_ADDRESS=my-namespace.acct.tmprl.cloud:7233
export TEMPORAL_CLOUD_NAMESPACE=my-namespace.acct
export TEMPORAL_CLOUD_API_KEY=...        # API-key auth; TLS enabled automatically
```

The same `create_temporal_client` handles self‑hosted and Cloud.

---

## 9. Observability

**Arize Cloud (LLM/agent traces):** set in `.env` and enable:
```bash
ARIZE_ENABLED=true
ARIZE_TRANSPORT=app            # app (direct) | collector (via OTel Collector)
ARIZE_OTLP_ENDPOINT=https://otlp.arize.com/v1
ARIZE_SPACE_ID=...
ARIZE_API_KEY=...
```
Traces go to Arize over OTLP with `space_id`/`api_key` headers; the project is
set via the `openinference.project.name` resource attribute. Set
`observability.instrument_llm: true` for rich LLM spans (prompts/tokens).

**Metrics → Prometheus → Grafana:** the OTel Collector exposes a Prometheus
endpoint (`:8889`); Prometheus scrapes it; Grafana auto‑provisions the datasource
and the **Temporal LangGraph Agent** dashboard. Metric families:
`agent.llm.*`, `agent.tool.*`, `agent.hitl.decisions`, `agent.chaos.injected`,
plus Temporal SDK metrics (`temporal_workflow_*`, `temporal_activity_*`,
`temporal_worker_task_slots_*`, …).

**Local endpoints (bundled compose):** Temporal UI `:8233`, OTLP `:4317/:4318`,
Collector metrics `:8889`, Prometheus `:9090`, Grafana `:3000`, Phoenix `:6006`.

**Self‑hosted Phoenix** is supported as an alternative to Arize Cloud
(`observability.phoenix.*`, transports `collector` or `app`).

---

## 10. Project layout

```
app/
  config/         one typed settings model + layered loader
  temporal/       unified client, runtime (SDK metrics), retry, A2A activity
  agent/          hello agent, Lyzr chat model, multi-agent pipeline
  workflows/      AgentWorkflow, OrderWorkflow, ApprovalWorkflow, A2AWorkflow
  platform/       hitl, a2a protocol, chaos engine
  integrations/   servicenow (simulator + real client)
  observability/  OTel traces/metrics, Arize/Phoenix, structured logging
  infrastructure/ health checks + docker compose lifecycle
  ui/             FastAPI control plane + single-page demo UI
  entrypoints/    worker, workflow, order, approve, a2a, a2a_server,
                  servicenow_agent, ui, infrastructure
config/           config.yaml, config.example.yaml, lyzr_agents.yaml
docker/           otel-collector.yaml, prometheus.yml, grafana/, Dockerfile
scripts/          services.sh, lyzr_provision.py
tests/            unit tests (mock Docker/OTLP/Temporal — no external services)
```

---

## 11. Testing

```bash
make test        # unit tests; no external services required
```

Covers: config parsing + env overrides, Temporal mode/cloud validation, agent &
tool construction, LLM provider selection (incl. mocked Lyzr), multi‑agent
pipeline, HITL gate logic, A2A protocol, ServiceNow simulator, chaos injection,
metrics/telemetry, UI control plane (faked Temporal client), infra health checks.

The build verifies **end‑to‑end at every milestone** against a real Temporal
server and the live Lyzr agents.

---

## 12. Glossary (for non-specialists)

- **Temporal** — durable workflow engine: your process survives crashes,
  retries failed steps, and can wait days for a human without losing state.
- **LangGraph** — framework for building agent reasoning as a graph of steps.
- **Lyzr** — a *model router*: each agent is registered in Lyzr, which picks the
  underlying LLM; our app calls Lyzr, so one key covers all model access.
- **Agent activity** — a nondeterministic step (LLM/tool/HTTP) run as a Temporal
  Activity so it can be retried and timed out safely.
- **HITL** — human‑in‑the‑loop: the workflow pauses for a person to approve.
- **A2A** — agent‑to‑agent: a standard way for one agent to call another
  (agent card + task endpoint), including third‑party systems.
- **OpenTelemetry / OTel Collector** — vendor‑neutral traces & metrics, routed
  to Arize, Prometheus, and Grafana.
- **Arize** — hosted LLM/agent observability (traces, evaluations).

---

## 13. Notes on the current Temporal SDK (vs. older examples)

Built against `temporalio==1.33.0`. Intentional differences from stale samples:

- **Worker SDK metrics** use `TelemetryConfig(metrics=OpenTelemetryConfig(...))`
  (native OTLP), not a `MetricBuffer → MetricsExporter → MeterProvider` chain.
  `attach_service_name=False` avoids a duplicate‑label clash with the collector.
- **LangGraph nodes must be module‑level** (the plugin keys on qualified name);
  models are injected at graph‑build time.
- **Conditional edges are `async`** so LangGraph does not use `run_in_executor`
  (unsupported in Temporal's workflow event loop).
- **Node state is normalized with `convert_to_messages`** — graph state crosses
  the activity boundary as plain dicts.

---

## 14. Troubleshooting

- **`temporal.mode=cloud requires ...`** — set cloud address/namespace/api_key.
- **Worker: "required services unavailable and auto_start=false"** — start infra
  (`make infra-up`) or set `infrastructure.auto_start: true`.
- **Order says `multi_agent.enabled is false`** — enable `multi_agent` in config
  or `MULTI_AGENT_ENABLED=true`.
- **Lyzr errors** — ensure `LYZR_API_KEY` is set and `python scripts/lyzr_provision.py`
  has created `config/lyzr_agents.yaml`.
- **No `temporal_*` metrics in Prometheus** — run a single worker; check the
  collector is reachable at the configured OTLP endpoint.
- **Arize** — a working setup exports with `SpanExportResult.SUCCESS`; check
  `ARIZE_SPACE_ID` / `ARIZE_API_KEY` if you see 401/403.
- **Ports already in use** — the bundled compose uses canonical ports; if you run
  your own Prometheus/Grafana elsewhere, point config/`.env` at those instead.

---

## 15. Agent Studio: guided multi-agent demo

The UI at http://localhost:8000 shows the actual agent sequence, activity inputs
and outputs, retry attempts, approval gates (including child workflows), and the
optional ServiceNow A2A handoff. Select a step for details, or switch to **Activity
log** and **Result**. The four scenario presets populate the request and fault
settings; approval rules and fault controls remain editable.

The configuration below is an optional local demo preset. For Arize Cloud, use
the Arize configuration described above and its environment overrides.

Use the same demo configuration for all three processes. Start infrastructure
first, then leave each process running in its own terminal:

```bash
docker compose up -d
APP_CONFIG_FILE=config/demo.yaml .venv/bin/python -m app.entrypoints.worker
APP_CONFIG_FILE=config/demo.yaml .venv/bin/python -m app.entrypoints.servicenow_agent --host 127.0.0.1
APP_CONFIG_FILE=config/demo.yaml .venv/bin/python -m app.entrypoints.ui
```

`config/demo.yaml` enables the six-agent pipeline, a local ServiceNow simulator,
Phoenix instrumentation, and the deterministic fake model. These are real
Temporal executions with demo model responses; no external ServiceNow tickets or
LLM API calls are made by this configuration. Existing environment overrides
still take precedence. The demo allows 30 minutes for a human decision within a
one-hour workflow execution timeout.

Progress is projected from Temporal history and pending activities. The UI does
not animate invented progress. Temporal may compact intermediate retry events;
the inspector shows the observed attempt count and last failure rather than an
invented event for each attempt. The approval gate follows the whole agent
pipeline; rejection completes the workflow with an **Order rejected** outcome.

The browser remembers up to 25 recent run IDs locally so a refresh or UI-process
restart can reconnect to them. This is a demo convenience, not a shared durable
run index. Detailed agent payloads are visible in the inspector, so use this
local control plane only with data appropriate for the demo audience.
