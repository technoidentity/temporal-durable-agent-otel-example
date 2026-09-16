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


class WorkflowConfig(BaseModel):
    execution_timeout_seconds: int = 300


class ActivityConfig(BaseModel):
    start_to_close_timeout_seconds: int = 60
    maximum_attempts: int = 3
    retry: RetryConfig = Field(default_factory=RetryConfig)


class TemporalConfig(BaseModel):
    mode: TemporalMode = TemporalMode.self_hosted
    self_hosted: SelfHostedConfig = Field(default_factory=SelfHostedConfig)
    cloud: CloudConfig = Field(default_factory=CloudConfig)
    task_queue: str = "langgraph-agent"
    workflow: WorkflowConfig = Field(default_factory=WorkflowConfig)
    activity: ActivityConfig = Field(default_factory=ActivityConfig)

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
    graph_name: str = "hello-agent"


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


class ObservabilityConfig(BaseModel):
    enabled: bool = True
    service_name: str = "temporal-langgraph-worker"
    otel: OtelConfig = Field(default_factory=OtelConfig)
    metrics: SignalToggle = Field(default_factory=SignalToggle)
    traces: SignalToggle = Field(default_factory=SignalToggle)
    logs: SignalToggle = Field(default_factory=SignalToggle)
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
    llm: LLMConfig = Field(default_factory=LLMConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    infrastructure: InfrastructureConfig = Field(default_factory=InfrastructureConfig)

    model_config = {"extra": "forbid"}
