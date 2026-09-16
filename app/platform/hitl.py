"""Human-in-the-loop primitives: serializable messages + deterministic gate.

These are shared by the inline gate (inside the order workflow) and the
dedicated ``ApprovalWorkflow``. Everything here is pure/deterministic so it is
safe to use in Temporal workflow code (no clock, IO, or environment access).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_PCT = re.compile(r"(\d+(?:\.\d+)?)\s*%")


@dataclass
class ApprovalRequest:
    """What a human is being asked to approve."""

    reason: str
    discount: float
    threshold: float
    details: str = ""


@dataclass
class ApprovalDecision:
    """The recorded outcome of an approval gate."""

    approved: bool
    approver: str = ""
    note: str = ""
    # How the decision was reached: human | timeout | auto (no approval needed).
    via: str = "human"


def parse_discount(text: str) -> float | None:
    """Extract the highest percent value mentioned in the text, if any.

    Deterministic (pure regex), so it is safe to call from workflow code.
    """
    matches = [float(m) for m in _PCT.findall(text or "")]
    return max(matches) if matches else None


def needs_approval(discount: float | None, threshold: float) -> bool:
    """True when the discount strictly exceeds the threshold."""
    return discount is not None and discount > threshold
