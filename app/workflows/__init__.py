"""Temporal workflows."""

from app.workflows.a2a_workflow import A2AWorkflow, A2AWorkflowInput
from app.workflows.agent_workflow import AgentWorkflow, AgentWorkflowInput
from app.workflows.approval_workflow import ApprovalWorkflow, ApprovalWorkflowInput
from app.workflows.order_workflow import OrderWorkflow, OrderWorkflowInput

__all__ = [
    "A2AWorkflow",
    "A2AWorkflowInput",
    "AgentWorkflow",
    "AgentWorkflowInput",
    "ApprovalWorkflow",
    "ApprovalWorkflowInput",
    "OrderWorkflow",
    "OrderWorkflowInput",
]
