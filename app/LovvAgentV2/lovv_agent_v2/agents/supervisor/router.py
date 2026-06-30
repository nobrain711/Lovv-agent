"""Conditional edge routing functions."""
from lovv_agent_v2.core.state import UnifiedAgentState

def route_next_action(state: UnifiedAgentState) -> str:
    """Return next node name deterministically based on state flags."""
    return "response_packager"
