#!/usr/bin/env python3
"""Provision the PepsiCo demo agent roster in Lyzr (idempotent).

Reads LYZR_API_KEY (and optional LYZR_BASE_URL / LYZR_MODEL) from the
environment or repo .env, ensures each roster agent exists (reusing by name),
and writes the resulting name -> agent_id map to config/lyzr_agents.yaml.

Usage:
    python scripts/lyzr_provision.py            # create/reuse + write map
    python scripts/lyzr_provision.py --health   # just check connectivity
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import httpx
import yaml

REPO = Path(__file__).resolve().parents[1]
DEFAULT_BASE = "https://agent-prod.studio.lyzr.ai"

# name -> (description, role, instructions, goal)
ROSTER: dict[str, tuple[str, str, str, str]] = {
    "pepsico-intake": (
        "Parses PepsiCo distributor order requests.",
        "Order intake specialist",
        "Extract product, quantity, requested discount %, and store/distributor "
        "from the request. Respond with a short structured summary.",
        "Produce a clean, structured order summary.",
    ),
    "pepsico-inventory": (
        "Assesses PepsiCo product inventory availability.",
        "Inventory analyst",
        "Given an order summary, state whether stock is sufficient and note any "
        "constraints or substitutions. Be concise.",
        "Report availability clearly.",
    ),
    "pepsico-pricing": (
        "Computes promotional pricing for distributor orders.",
        "Pricing and promotions analyst",
        "Given quantity and requested discount, decide the final discount. "
        "Discounts above 15% require human approval; say so explicitly.",
        "Return final pricing and whether approval is required.",
    ),
    "pepsico-fulfillment": (
        "Plans fulfillment and flags risks.",
        "Fulfillment planner",
        "Plan fulfillment for the order and flag any risk that would require "
        "opening a support case (e.g. stock shortfall, delivery constraint).",
        "Return a fulfillment plan and any risk flags.",
    ),
    "pepsico-account": (
        "Summarizes distributor account context.",
        "Account specialist",
        "Summarize the distributor account context relevant to this order in "
        "one or two sentences.",
        "Provide brief account context.",
    ),
    "pepsico-supervisor": (
        "Coordinates the PepsiCo order fulfillment agent team.",
        "Supervisor",
        "Given the outputs of intake, inventory, pricing, fulfillment and "
        "account agents, write a concise final outcome for the distributor.",
        "Deliver a clear final decision and summary.",
    ),
}


def _load_env() -> None:
    env = REPO / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def _client() -> tuple[httpx.Client, str]:
    key = os.environ.get("LYZR_API_KEY", "")
    if not key:
        sys.exit("LYZR_API_KEY is not set (put it in .env)")
    base = os.environ.get("LYZR_BASE_URL", DEFAULT_BASE).rstrip("/")
    client = httpx.Client(
        base_url=base,
        headers={"Content-Type": "application/json", "x-api-key": key},
        timeout=30.0,
    )
    return client, base


def list_agents(client: httpx.Client) -> list[dict]:
    r = client.get("/v3/agents/")
    r.raise_for_status()
    return r.json()


def create_agent(client: httpx.Client, name: str, spec: tuple, model: str) -> str:
    desc, role, instr, goal = spec
    payload = {
        "name": name,
        "description": desc,
        "agent_role": role,
        "agent_instructions": instr,
        "agent_goal": goal,
        "features": [],
        "tools": [],
        "response_format": {"type": "text"},
        "provider_id": "OpenAI",
        "model": model,
        "top_p": 0.9,
        "temperature": 0.7,
        "llm_credential_id": "lyzr_openai",
        "managed_agents": [],
    }
    r = client.post("/v3/agents/", json=payload)
    if r.status_code >= 300:
        raise RuntimeError(f"create {name} failed: {r.status_code} {r.text}")
    data = r.json()
    return str(data.get("agent_id") or data.get("id") or data.get("_id"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--health", action="store_true", help="only check connectivity")
    ap.add_argument("--model", default=os.environ.get("LYZR_MODEL", "gpt-4o-mini"))
    args = ap.parse_args()

    _load_env()
    client, base = _client()

    existing = list_agents(client)
    print(f"[health] GET /v3/agents/ -> {len(existing)} agent(s) at {base}")
    if args.health:
        return

    by_name = {a.get("name"): str(a.get("_id")) for a in existing}
    result: dict[str, str] = {}
    for name, spec in ROSTER.items():
        if name in by_name:
            result[name] = by_name[name]
            print(f"[reuse]  {name} -> {by_name[name]}")
        else:
            aid = create_agent(client, name, spec, args.model)
            result[name] = aid
            print(f"[create] {name} -> {aid}")

    out = REPO / "config" / "lyzr_agents.yaml"
    out.write_text(
        yaml.safe_dump(
            {"base_url": base, "model": args.model, "agents": result},
            sort_keys=False,
        )
    )
    print(f"[write]  {out.relative_to(REPO)} ({len(result)} agents)")


if __name__ == "__main__":
    main()
