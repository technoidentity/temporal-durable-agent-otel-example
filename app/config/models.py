"""Strongly typed configuration models for the whole application.

There is exactly one root model, :class:`AppSettings`. Every other model is a
nested section of it. Nothing in the application should read environment
variables or hardcode addresses directly; it should receive a fully validated
``AppSettings`` (or the relevant sub-section) via dependency injection.

Precedence (highest first) is enforced by ``app.config.loader``:

    environment variables  >  config YAML  >  safe defaults (this module)
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, model_validator


class Environment(str, Enum):
    local = "local"
    development = "development"
    staging = "staging"
    production = "production"


class TemporalMode(str, Enum):
    self_hosted = "self_hosted"
    cloud = "cloud"


class HITLMode(str, Enum):
    # Gate handled inside the order workflow (signal/query/timer on the workflow).
    inline = "inline"
    # Gate delegated to a dedicated, reusable ApprovalWorkflow (child workflow).
    child = "child"


class OnTimeout(str, Enum):
    reject = "reject"
    approve = "approve"


class OtelProtocol(str, Enum):
    grpc = "grpc"
    http = "http"


class LLMProvider(str, Enum):
    openai = "openai"
    # ``lyzr`` routes reasoning through the Lyzr Agent API (the model router):
    # the underlying model is configured on the Lyzr agent, so the Lyzr key
    # covers LLM access. Returns text (no OpenAI-style tool_calls).
    lyzr = "lyzr"
    # ``ollama`` is a local, real LLM for offline development. Tool-calling
    # capable models (e.g. llama3.1, qwen2.5) support the tool flow.
    ollama = "ollama"
    # ``fake`` is a deterministic, offline tool-calling model. It lets the full
    # workflow -> agent -> tool -> agent path run end to end without an API key.
    fake = "fake"


# --------------------------------------------------------------------------- #
# app
# --------------------------------------------------------------------------- #
class AppConfig(BaseModel):
    name: str = "temporal-langgraph-agent"
    environment: Environment = Environment.local


# --------------------------------------------------------------------------- #
# temporal
# --------------------------------------------------------------------------- #
class SelfHostedConfig(BaseModel):
    address: str = "localhost:7233"
    namespace: str = "default"


class CloudConfig(BaseModel):
    address: str = ""
    namespace: str = ""
    api_key: str = ""
    tls_enabled: bool = True


class RetryConfig(BaseModel):
    initial_interval_seconds: float = 1.0
    backoff_coefficient: float = 2.0
    maximum_interval_seconds: float = 30.0
    maximum_attempts: int = 3
    # Errors that should NOT be retried (invalid input / config / bad request).
    # Retrying these just burns attempts and delays a clear failure.
    non_retryable_error_types: list[str] = Field(
        default_factory=lambda: ["ValueError", "TypeError", "KeyError"]
    )


class WorkflowConfig(BaseModel):
    # Must exceed hitl.approval_timeout_seconds (a durable human wait counts
    # against the workflow's execution timeout). Enforced by AppSettings.
    execution_timeout_seconds: int = 604800  # 7 days


class ActivityConfig(BaseModel):
    start_to_close_timeout_seconds: int = 60
    # A hung activity is invisible until start_to_close elapses and cancellation
    # cannot be delivered without heartbeats, so set a heartbeat timeout too.
    heartbeat_timeout_seconds: int = 30
    retry: RetryConfig = Field(default_factory=RetryConfig)


class TemporalConfig(BaseModel):
    mode: TemporalMode = TemporalMode.self_hosted
    self_hosted: SelfHostedConfig = Field(default_factory=SelfHostedConfig)
    cloud: CloudConfig = Field(default_factory=CloudConfig)
    task_queue: str = "langgraph-agent"
    workflow: WorkflowConfig = Field(default_factory=WorkflowConfig)
    activity: ActivityConfig = Field(default_factory=ActivityConfig)
    # Emit typed Search Attributes for pending approvals (review L2). Off by
    # default: the attributes must first be registered on the namespace
    # (`python -m app.entrypoints.infrastructure register-search-attributes`),
    # otherwise the server rejects the upsert and fails the workflow task.
    search_attributes_enabled: bool = False

    @property
    def address(self) -> str:
        """Resolved server address for the active mode."""
        return self.cloud.address if self.mode is TemporalMode.cloud else self.self_hosted.address

    @property
    def namespace(self) -> str:
        """Resolved namespace for the active mode."""
        return (
            self.cloud.namespace if self.mode is TemporalMode.cloud else self.self_hosted.namespace
        )

    @model_validator(mode="after")
    def _validate_mode(self) -> "TemporalConfig":
        if self.mode is TemporalMode.cloud:
            missing = [
                name
                for name, value in (
                    ("temporal.cloud.address", self.cloud.address),
                    ("temporal.cloud.namespace", self.cloud.namespace),
                    ("temporal.cloud.api_key", self.cloud.api_key),
                )
                if not value
            ]
            if missing:
                raise ValueError(
                    "temporal.mode=cloud requires: " + ", ".join(missing)
                )
        return self


# --------------------------------------------------------------------------- #
# langgraph
# --------------------------------------------------------------------------- #
class LangGraphConfig(BaseModel):
    # The single-agent hello graph (tool-calling demo). Disable it to run a
    # pure multi-agent worker (e.g. with a non-tool-calling provider like Lyzr).
    enabled: bool = True
    graph_name: str = "hello-agent"


# --------------------------------------------------------------------------- #
# multi-agent
# --------------------------------------------------------------------------- #
class MultiAgentConfig(BaseModel):
    """The PepsiCo multi-agent order pipeline.

    ``pipeline`` selects and orders roles from the known roster. Each role maps
    to a Lyzr agent id via ``lyzr_agents_file`` (key = ``name_prefix`` + role)
    when the LLM provider is ``lyzr``; other providers reuse the global llm.
    """

    enabled: bool = False
    graph_name: str = "pepsico-order"
    pipeline: list[str] = Field(
        default_factory=lambda: [
            "intake",
            "inventory",
            "pricing",
            "fulfillment",
            "account",
            "supervisor",
        ]
    )
    lyzr_agents_file: str = "config/lyzr_agents.yaml"
    name_prefix: str = "pepsico-"


# --------------------------------------------------------------------------- #
# human-in-the-loop
# --------------------------------------------------------------------------- #
class HITLConfig(BaseModel):
    """Human-in-the-loop approval gate. All values are overridable per run so
    the demo UI can change them live."""

    enabled: bool = True
    mode: HITLMode = HITLMode.inline
    # A requested discount strictly greater than this (percent) needs approval.
    discount_threshold: float = 15.0
    # How long the workflow waits durably for a human decision.
    approval_timeout_seconds: int = 86400
    on_timeout: OnTimeout = OnTimeout.reject


# --------------------------------------------------------------------------- #
# agent-to-agent (A2A)
# --------------------------------------------------------------------------- #
class A2AConfig(BaseModel):
    """Agent-to-agent connectivity. ``agents`` maps a logical name to the base
    URL of a remote A2A agent (each exposes an agent card + task endpoint)."""

    enabled: bool = False
    agents: dict[str, str] = Field(default_factory=dict)
    call_timeout_seconds: int = 30


# --------------------------------------------------------------------------- #
# third-party systems
# --------------------------------------------------------------------------- #
class ServiceNowConfig(BaseModel):
    """ServiceNow integration. ``simulator`` uses a local seeded instance;
    ``real`` points at a ServiceNow PDI (credentials from env). Swapping is a
    config change only."""

    enabled: bool = False
    mode: str = "simulator"  # simulator | real
    base_url: str = ""  # real instance, e.g. https://devXXXXX.service-now.com
    username: str = ""
    password: str = ""
    table: str = "incident"
    # Where the ServiceNow A2A agent listens (used by the order flow).
    a2a_url: str = "http://localhost:8801"
    open_incident_on_risk: bool = True
    risk_keywords: list[str] = Field(
        default_factory=lambda: [
            "risk",
            "shortfall",
            "delay",
            "escalate",
            "case",
            "unable",
            "insufficient",
            "out of stock",
        ]
    )


class ThirdPartyConfig(BaseModel):
    servicenow: ServiceNowConfig = Field(default_factory=ServiceNowConfig)


# --------------------------------------------------------------------------- #
# demo UI
# --------------------------------------------------------------------------- #
class UIConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000


# --------------------------------------------------------------------------- #
# chaos / fault injection
# --------------------------------------------------------------------------- #
class ChaosConfig(BaseModel):
    """Fault injection defaults. Everything is overridable per run so the demo
    UI can flip faults on and off live."""

    enabled: bool = False
    target: str = ""  # agent role to affect (e.g. "inventory")
    mode: str = "none"  # none | transient_error | permanent_error | latency
    attempts: int = 1  # apply on attempts <= N (0 = every attempt)
    latency_seconds: float = 0.0
    force_hitl: bool = False  # trip the approval gate regardless of discount

    def as_spec(self) -> dict:
        if not self.enabled:
            return {}
        return {
            "target": self.target,
            "mode": self.mode,
            "attempts": self.attempts,
            "latency_seconds": self.latency_seconds,
            "force_hitl": self.force_hitl,
        }


# --------------------------------------------------------------------------- #
# llm
# --------------------------------------------------------------------------- #
class LLMConfig(BaseModel):
    provider: LLMProvider = LLMProvider.openai
    model: str = "gpt-4o-mini"
    api_key: str = ""
    # Optional custom endpoint (OpenAI-compatible gateways, Azure, local,
    # Ollama at http://localhost:11434, ...).
    base_url: str = ""
    temperature: float = 0.0
    # Lyzr routing: the agent to invoke and a stable caller id. base_url/api_key
    # above are reused for the Lyzr endpoint and x-api-key.
    lyzr_agent_id: str = ""
    lyzr_user_id: str = "devex-demo"

    @model_validator(mode="after")
    def _validate_provider(self) -> "LLMConfig":
        if self.provider is LLMProvider.openai and not self.api_key:
            # Not fatal at construction time: the worker validates before it
            # builds the real client, so unit tests can still parse config.
            pass
        return self


# --------------------------------------------------------------------------- #
# observability
# --------------------------------------------------------------------------- #
class OtelConfig(BaseModel):
    enabled: bool = True
    endpoint: str = "http://localhost:4317"
    protocol: OtelProtocol = OtelProtocol.grpc


class SignalToggle(BaseModel):
    enabled: bool = True


class TemporalCloudMetricsConfig(BaseModel):
    enabled: bool = False
    endpoint: str = "https://metrics.temporal.io/v1/metrics"
    api_key: str = ""

    @model_validator(mode="after")
    def _validate(self) -> "TemporalCloudMetricsConfig":
        if self.enabled and not self.api_key:
            raise ValueError(
                "observability.temporal_cloud_metrics.enabled=true requires an api_key "
                "(set TEMPORAL_METRICS_API_KEY)"
            )
        return self


class PhoenixConfig(BaseModel):
    """Arize Phoenix (self-hosted) for LLM/agent trace analysis.

    Two transports are supported:
    * ``collector`` (ideal): the OTel Collector forwards traces to the Phoenix
      service (full container stack).
    * ``app``: the application exports spans directly to ``otlp_endpoint`` — used
      when Phoenix runs outside Docker (e.g. the pip package on the host).
    """

    enabled: bool = False
    transport: str = "collector"  # collector | app
    endpoint: str = "http://localhost:6006"  # Phoenix UI (for links)
    otlp_endpoint: str = "http://localhost:6006/v1/traces"  # app-direct OTLP HTTP


class ArizeConfig(BaseModel):
    """Arize Cloud (AX) for LLM/agent trace analysis. Traces are sent over OTLP
    with ``space_id`` + ``api_key`` headers; the project is set via the
    ``openinference.project.name`` resource attribute.

    Two transports (same idea as Phoenix): ``app`` exports directly from the
    application; ``collector`` routes via the OTel Collector's otlphttp/arize
    exporter (ideal for a shared pipeline)."""

    enabled: bool = False
    transport: str = "app"  # app | collector
    endpoint: str = "https://otlp.arize.com/v1"
    api_key: str = ""
    space_id: str = ""
    project_name: str = "temporal-langgraph-agent"


class ObservabilityConfig(BaseModel):
    enabled: bool = True
    service_name: str = "temporal-langgraph-worker"
    otel: OtelConfig = Field(default_factory=OtelConfig)
    phoenix: PhoenixConfig = Field(default_factory=PhoenixConfig)
    arize: ArizeConfig = Field(default_factory=ArizeConfig)
    instrument_llm: bool = False
    metrics: SignalToggle = Field(default_factory=SignalToggle)
    traces: SignalToggle = Field(default_factory=SignalToggle)
    temporal_worker_metrics: SignalToggle = Field(default_factory=SignalToggle)
    temporal_cloud_metrics: TemporalCloudMetricsConfig = Field(
        default_factory=TemporalCloudMetricsConfig
    )
    # Prompt/response bodies are never logged unless this is explicitly enabled.
    log_prompts: bool = False

    @property
    def traces_active(self) -> bool:
        return self.enabled and self.otel.enabled and self.traces.enabled

    @property
    def metrics_active(self) -> bool:
        return self.enabled and self.otel.enabled and self.metrics.enabled

    @property
    def worker_metrics_active(self) -> bool:
        return self.metrics_active and self.temporal_worker_metrics.enabled


# --------------------------------------------------------------------------- #
# infrastructure
# --------------------------------------------------------------------------- #
class InfraServices(BaseModel):
    temporal: bool = True
    otel_collector: bool = True
    prometheus: bool = True
    grafana: bool = True


class InfrastructureConfig(BaseModel):
    auto_start: bool = True
    docker_compose_file: str = "docker-compose.yml"
    startup_timeout_seconds: int = 120
    services: InfraServices = Field(default_factory=InfraServices)
    # Endpoints used purely for health checks (never used to build clients).
    temporal_ui_url: str = "http://localhost:8233"
    prometheus_url: str = "http://localhost:9090"
    grafana_url: str = "http://localhost:3000"


# --------------------------------------------------------------------------- #
# root
# --------------------------------------------------------------------------- #
class AppSettings(BaseModel):
    """The single configuration object for the entire application."""

    app: AppConfig = Field(default_factory=AppConfig)
    temporal: TemporalConfig = Field(default_factory=TemporalConfig)
    langgraph: LangGraphConfig = Field(default_factory=LangGraphConfig)
    multi_agent: MultiAgentConfig = Field(default_factory=MultiAgentConfig)
    hitl: HITLConfig = Field(default_factory=HITLConfig)
    a2a: A2AConfig = Field(default_factory=A2AConfig)
    third_party: ThirdPartyConfig = Field(default_factory=ThirdPartyConfig)
    chaos: ChaosConfig = Field(default_factory=ChaosConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    infrastructure: InfrastructureConfig = Field(default_factory=InfrastructureConfig)

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _validate_timeouts(self) -> "AppSettings":
        # A human-in-the-loop wait counts against the workflow execution timeout.
        # If the gate can wait longer than the workflow may run, Temporal
        # terminates the order before anyone can approve it (see review B1).
        if self.hitl.enabled and (
            self.hitl.approval_timeout_seconds >= self.temporal.workflow.execution_timeout_seconds
        ):
            raise ValueError(
                "hitl.approval_timeout_seconds "
                f"({self.hitl.approval_timeout_seconds}) must be less than "
                "temporal.workflow.execution_timeout_seconds "
                f"({self.temporal.workflow.execution_timeout_seconds}); otherwise the "
                "approval gate is terminated before it can resolve."
            )
        return self
