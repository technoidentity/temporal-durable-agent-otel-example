# Temporal pre-demo review — response

Response to the 19-issue durable-execution review (3 blockers · 6 high · 6 medium
· 4 low). All 19 findings are now addressed and verified.

## Why we missed these (root causes)

1. **Tests bypassed Temporal.** The "end-to-end" tests called
   `build_graph(...).compile().ainvoke(...)` *outside* the LangGraph plugin, so
   the payload boundary, activity timeouts, the approval gate, and child mode
   were never exercised. Messages stayed as real objects, so assertions passed
   for the wrong reason. This is precisely how **B1, B2, and H3** shipped.
   → Fixed by adding `WorkflowEnvironment` tests that run the workflow through
   the real plugin (`tests/test_workflow_env.py`, review **M1**).
2. **No cross-field config validation.** The execution timeout and the approval
   wait were set in separate sections and never compared (**B1**).
   → Added an `AppSettings` validator that rejects the inversion.
3. **Feature breadth over durability hardening.** While building multi-agent /
   HITL / A2A / chaos / UI, we under-invested in idempotency (**B3**), retry
   classification (**H5**), heartbeats (**H4**), and graceful shutdown (**H6**).
4. **Followed the plugin's worker-only example** and forgot client registration
   (**H1**); and moved the A2A call *into* the agent node for a nice
   "agent-makes-the-call" story without accounting for retry-safety (**B3**).

## Status of every finding

| ID | Issue | Status |
|----|-------|--------|
| **B1** | Execution timeout shorter than approval timeout | **Fixed** — execution timeout raised above the gate + `AppSettings` validator rejects the inversion. Verified: 20% order gates and completes on approval. |
| **B2** | Child-mode approvals signalled the wrong workflow | **Fixed** — `approve` CLI auto-detects and targets the child `ApprovalWorkflow`. Verified: child-mode approve resolves (`…-approval`). |
| **B3** | Non-idempotent side effect in a retryable activity | **Fixed** — ServiceNow call moved out of the LLM node into a dedicated activity keyed deterministically (`<wf-id>-servicenow`); the store upserts on `correlation_id`. Verified: retried create returns the same ticket. |
| **H1** | Plugin on Worker but not Client | **Fixed** — registered on the client; the worker inherits it (passing to both double-registers activities). |
| **H2** | Sync blocking I/O, no activity executor | **Fixed** — explicit `ThreadPoolExecutor` set as the loop default executor + `max_concurrent_activities`. |
| **H3** | `.content` on a possibly-dict message | **Fixed** — messages normalized with `convert_to_messages` in `AgentWorkflow.run` and the router before use. |
| **H4** | No heartbeat timeout | **Fixed** — `heartbeat_timeout` added to activity options (config-driven). |
| **H5** | Everything retryable; tool KeyError | **Fixed** — `non_retryable_error_types` (ValueError/TypeError/KeyError); unknown tool returns an error `ToolMessage` instead of raising. |
| **H6** | No graceful shutdown | **Fixed** — `graceful_shutdown_timeout` on the Worker + `stop_grace_period` on compose services. (B3 remains the real dup-prevention.) |
| **M1** | No WorkflowEnvironment/Replayer tests | **Fixed** — `WorkflowEnvironment` tests run the order workflow through the real plugin (gate + payload boundary). Replayer test tracked as a follow-up. |
| **M2** | No versioning strategy | **Fixed** — the post-ship ServiceNow leg is gated behind `workflow.patched("order-servicenow-incident-leg")` so pre-patch histories replay deterministically; Worker Versioning (build IDs) documented as the production strategy below. |
| **M3** | Random workflow IDs discard dedup | **Fixed** — start calls set `WorkflowIDReusePolicy.REJECT_DUPLICATE`; pass a business key as the workflow id (`--workflow-id`) to dedupe double-submits. |
| **M4** | Child workflow started with no policies | **Fixed** — explicit `execution_timeout`, `retry_policy`, `id_reuse_policy`, `parent_close_policy`. |
| **M5** | Dead config keys | **Fixed** — removed `activity.maximum_attempts` (outer) and `observability.logs`; defaulted the collector's Arize exporter endpoint. |
| **M6** | Unbounded agent loop / payload size | **Fixed (loop)** — `recursion_limit` on the hello-agent with a clean `GraphRecursionError` fallback. Payload-size measurement noted as follow-up. |
| **L1** | Gate should be an Update, not signal+query+poll | **Fixed** — `decide_update` (`@workflow.update` + validator) on both `OrderWorkflow` and `ApprovalWorkflow` confirms the decision atomically and rejects a decision on a closed/already-decided gate; the approve CLI and UI call the update (no pre-query). The first-wins signal is retained for compatibility. |
| **L2** | No Search Attributes for pending approvals | **Fixed** — typed `PepsicoApprovalPending` / `PepsicoApprovalReason` upserted while the gate is open (config-gated by `temporal.search_attributes_enabled`; register once with `infrastructure register-search-attributes`), so pending approvals are one `list_workflows` call. |
| **L3** | Swallowed query failures; status by enum name | **Fixed** — status branches compare the typed `WorkflowExecutionStatus` enum (not `.name` strings); the pending-query catch is narrowed to `WorkflowQueryFailedError`/`RPCError` so unexpected errors surface. |
| **L4** | Runtime only on the worker | **Fixed** — client entrypoints (order, workflow, UI) create the runtime too, so client-side SDK metrics are emitted. |

## Versioning strategy (M2)

The patch marker handles a single additive change safely. The production answer
to "how do you deploy a change to a running agent" is **Worker Versioning with
build IDs**: pin each worker to a build id, roll out a new build, and let
in-flight runs finish on the old one while new runs pin to the new default.
Editing `multi_agent.pipeline` changes the command sequence for in-flight runs,
so any such change ships either behind a new `workflow.patched(...)` marker or a
new build id — never as an unguarded edit.

## Remaining follow-ups (nice-to-have, not blocking)

- **M1 remainder** — a Replayer test over a captured history (the
  `WorkflowEnvironment` tests cover the live path today).
- **M6 remainder** — measure/limit payload size explicitly (the recursion limit
  bounds the loop today).
- **L1/L2 note** — the time-skipping test server (Java 1.16.0) predates Workflow
  Update and custom Search Attributes, so those paths are covered by unit tests
  and the UI control-plane tests rather than the `WorkflowEnvironment` suite.

## What was already correct
`workflow.unsafe.imports_passed_through()` in all workflow modules; no clock/env/
IO in workflow code; `wait_condition(..., timeout=)` with the `asyncio.TimeoutError`
catch; idempotent first-wins signal handlers; a read-only, non-blocking query
handler; a pure `parse_discount`; a deterministic child workflow id; per-node
`execute_in`; and `chaos._current_attempt()` reading `activity.info().attempt`.
