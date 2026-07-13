"""Shared in-process tool package for LOVV Agent V2.

Consolidates tool wrappers, runtime containers/protocols, factories, runtime
extractors, and Gateway-ready contracts that used to be scattered across
per-agent ``tools.py`` modules. This package is a shared code boundary, not
an AgentCore Gateway and not a network protocol boundary - see
docs/specs/v2/LOVV_V2_TOOL_CODE_CONSOLIDATION_SPEC.md.

Import order below follows the internal dependency chain
(``destination_search`` -> ``runtime_containers`` -> ``factories`` /
``runtime_extractors``) so importing this package cannot trigger a circular
partial-initialization import.
"""

from __future__ import annotations

from lovv_agent_v2.tools.contracts import (
    ContractValidationError,
    DestinationSearchRequest,
    DestinationSearchResponse,
    SavedItinerarySignalsRequest,
    SavedItinerarySignalsResponse,
)
from lovv_agent_v2.tools.destination_search import (
    RESPONSIBILITY,
    TOOL_NAME,
    DestinationSearchTool,
    build_attraction_filter,
    build_attraction_search_request,
)
from lovv_agent_v2.tools.runtime_containers import (
    DEFAULT_SCHEMA_RETRY_LIMIT,
    CitySelectScoringTools,
    CitySelectTools,
    DestinationSearchPort,
    EmbeddingPort,
    FestivalCandidateLookupTool,
    FestivalVerifierTools,
    IntentPromptRuntime,
    ItineraryExplanationRuntime,
    PlannerRuntimeTools,
)
from lovv_agent_v2.tools.factories import (
    build_city_select_scoring_tools,
    build_city_select_tools,
    build_default_city_select_scoring_tools,
    build_default_city_select_tools,
    build_festival_verifier_tools,
)
from lovv_agent_v2.tools.runtime_extractors import (
    intent_prompt_runtime_from_state,
    itinerary_explanation_runtime_from_state,
    runtime_tools_from_value,
)
from lovv_agent_v2.tools.saved_itinerary_signals import (
    RdsSavedItinerarySignalsTool,
    RdsSavedItinerarySignalsToolConfig,
    SqlFetchClient,
)
from lovv_agent_v2.tools.travel_time import travel_time_provider_from_value

__all__ = [
    "ContractValidationError",
    "DestinationSearchRequest",
    "DestinationSearchResponse",
    "SavedItinerarySignalsRequest",
    "SavedItinerarySignalsResponse",
    "RESPONSIBILITY",
    "TOOL_NAME",
    "DestinationSearchTool",
    "build_attraction_filter",
    "build_attraction_search_request",
    "DEFAULT_SCHEMA_RETRY_LIMIT",
    "CitySelectScoringTools",
    "CitySelectTools",
    "DestinationSearchPort",
    "EmbeddingPort",
    "FestivalCandidateLookupTool",
    "FestivalVerifierTools",
    "IntentPromptRuntime",
    "ItineraryExplanationRuntime",
    "PlannerRuntimeTools",
    "build_city_select_scoring_tools",
    "build_city_select_tools",
    "build_default_city_select_scoring_tools",
    "build_default_city_select_tools",
    "build_festival_verifier_tools",
    "intent_prompt_runtime_from_state",
    "itinerary_explanation_runtime_from_state",
    "runtime_tools_from_value",
    "RdsSavedItinerarySignalsTool",
    "RdsSavedItinerarySignalsToolConfig",
    "SqlFetchClient",
    "travel_time_provider_from_value",
]
