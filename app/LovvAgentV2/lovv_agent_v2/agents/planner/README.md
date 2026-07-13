# Planner Agent

Planner turns a selected city into an in-city itinerary.

Read in this order:

1. `subgraph.py` - parent graph entrypoint and local planner graph shape.
2. `state_adapter.py` - `UnifiedAgentState` to planner request/result boundary.
3. `agent.py` - deterministic planner core.
4. `tools.py` - planner runtime capability contracts.
5. `steps/` - implementation details for each subgraph step.

## Shape

The planner root keeps only files that are useful from outside the planner or
from the local LangGraph subgraph:

`subgraph.py`
wires the local step graph:

1. `retrieve_places`
2. `route_days`
3. `assemble_itinerary`
4. optional `retry_alternative_city`

`state_adapter.py`
is the only planner module that should understand planner scratch and graph
state adaptation.

`agent.py`
owns the core planner orchestration. It receives `PlannerAgentRequest` and
`PlannerAgentTools`, then retrieves places, selects a working set, and routes
the itinerary.

`tools.py`
defines the runtime tool protocol consumed directly by `agent.py`.

## Internal Packages

`state/`
contains state-facing helpers. `context.py` parses graph state into planner
inputs, and `scratch.py` owns planner-local scratch read/write helpers.

`domain/`
contains planner domain value normalization. `place_model.py` converts raw
candidate payloads into `PlannerPlace` objects used by selection and routing.

`external/`
contains external provider adapters and contracts that are not the planner
orchestration itself. Travel-time contracts, ORS integration, ORS result
normalization, AgentCore credential lookup, and the ORS helper module live here.

## Step Packages

`steps/retrieve_places/`
contains festival seed conversion used during place retrieval.

`steps/route_days/`
contains selection, theme quota, subtype diversity, travel metrics, and day
routing policies.

`steps/assemble_itinerary/`
builds `planner_output`, validation, audit, notices, and fallback metadata.

`steps/retry_alternative_city/`
detects thin primary-city itineraries and swaps state to the alternative city
when city-select supplied one.

## Rule Of Thumb

Change graph wiring in `subgraph.py`.
Change state shape in `state_adapter.py` or `state/context.py`.
Change planning behavior in `agent.py` or the matching `steps/` package.
Change runtime contracts in `tools.py`.
Change provider implementations in `external/`.
