from __future__ import annotations

from lovv_agent_v2.agents.mock_contract.nodes import mock_intent_node, mock_profile_node
from lovv_agent_v2.core.graph import compile_v2_graph_with_nodes


def compile_v2_mock_graph(checkpointer: object | None = None) -> object:
    return compile_v2_graph_with_nodes(
        intent_handler=mock_intent_node,
        profile_handler=mock_profile_node,
        checkpointer=checkpointer,
    )


__all__ = ["compile_v2_mock_graph"]
