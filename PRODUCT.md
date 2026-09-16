# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Customer demo audiences, with drill-down details for technical questions. Confirmed by the user on 2026-09-16.

## Product Purpose

Demonstrate how a distributor request passes through a configurable LangGraph agent pipeline executed as durable Temporal activities, then an optional human approval and ServiceNow incident handoff.

## Capabilities and Constraints

Six default roles: intake, inventory, pricing, fulfillment, account, supervisor. The configured pipeline is sequential. The approval gate runs after the agent pipeline, inline or in a child workflow. Approved fulfillment risk can open an incident through A2A. Fault injection supports transient errors, permanent errors, and latency. The fake model echoes prompts and does not establish business facts. Run status and activity progress must come from Temporal, never a simulated animation. Preserve configuration controls and links to Temporal, Grafana, Prometheus, and Phoenix.

## Evidence on Hand

The existing app and the original browser run pepsico-order-bbd520ad1051 completed all six agents and an inline approval on 2026-09-16. This is a local demonstration, not production validation.

## Product Principles

- Lead with the order journey; disclose technical details on selection.
- Clearly distinguish demo responses from real model output.
- Distinguish a completed workflow from a rejected business decision.
- Show actual execution and retry evidence.
