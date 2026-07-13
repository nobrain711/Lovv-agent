# City Select Agent

City Select chooses the destination city and prepares the city-level evidence that
the planner will use. It is implemented as a small LangGraph subgraph with two
nodes:

1. `retrieval`
2. `scoring_and_selection`

The graph-facing entry point is `subgraph.py`; the parent V2 graph imports only
`compile_city_select_subgraph`.

## Runtime Flow

`subgraph.py`
builds the local 2-node graph.

`nodes.py`
adapts `UnifiedAgentState` into agent requests and writes the resulting
`city_select` state group.

`retrieval/agent.py`
runs retrieval. It validates festival-gated city IDs, builds the embedding query,
retrieves candidate attractions, merges duplicates, and prunes cities by theme
coverage.

`scoring/agent.py`
runs scoring and final city selection. It scores survived city groups, ranks
cities, chooses the selected city, packages seeds, fallback city, planner hints,
and audits.

`tools.py`
contains runtime adapters for AWS-backed search and lookup:

- `DestinationSearchTool` wraps S3 Vector attraction search.
- `CitySelectTools` groups vector search, DynamoDB lookup, and embeddings.
- `CitySelectScoringTools` provides DynamoDB lookup for scoring enrichment.

## File Map

`domain/contracts.py`
defines city-select domain contracts: candidate records, context, theme splitting,
and mode resolution.

`retrieval/policy.py`
normalizes vector candidates and city-select input. It owns low-level candidate
shape helpers and city pruning primitives.

`retrieval/flow.py`
contains retrieval orchestration helpers: query text, duplicate merging,
allowed-city handling, failure payloads, and retrieval audit payloads.

`scoring/service.py`
keeps the public scoring facade: `ScoringTool`, `score_place`, and `score_city`.

`scoring/service_types.py`
defines place and city score result payloads.

`scoring/service_validation.py`
normalizes scoring inputs from mappings, objects, and metadata payloads.

`scoring/service_candidates.py`
coerces scored place payloads and computes candidate-level scoring helpers.

`scoring/service_geo.py`
owns distance and trip-duration penalty calculations.

`scoring/service_theme.py`
owns scored-theme filtering and profile theme-weight normalization.

`scoring/ranking.py`
scores groups and produces ranked city candidates.

`scoring/payloads.py`
packages selected city evidence, planner seeds, passthrough data, and reason
codes.

`scoring/city_payload.py`
builds the selected-city payload from ranked evidence.

`scoring/audit.py`
packages explainable scoring audit output.

`scoring/failures.py`
packages terminal city-select failures.

## State Contract

Input is expected at:

- `state.intent.city_select_input`
- `state.festival_gate.allowed_city_ids` when `include_festivals` is true

Output is written to:

- `state.city_select.city_selection_result`
- `state.city_select.status`
- `state.city_select.retrieval_audit`
- `state.city_select.scoring_audit`
- `state.city_select.clarification`

Planner consumes `city_selection_result.selected_city`, `seeds`,
`representative_seed`, `alternative_city`, and `planner_hints`.

## Change Guide

Change retrieval filters or AWS query shape in `tools.py` and
`retrieval/flow.py`.

Change city ranking math in `scoring/service.py` or `scoring/ranking.py`.

Change place allocation in the planner route-days package. City Select only
chooses the city and emits planner seeds.

Change response-facing city-select payload shape in `scoring/payloads.py`.

Change graph wiring only in `subgraph.py` or `nodes.py`.

## Tests

Relevant tests live mostly under `tests/v2`:

- destination search and city-select behavior
- supervisor graph routing
- generation-to-planner smoke paths

For focused checks, start with city-select and graph routing tests before running
broader smoke scripts.
