# Response Packager Agent

Response Packager turns internal V2 state into the final API-facing response. It
also hosts the itinerary explanation enrichment node that runs between Planner
and final packaging.

## Runtime Flow

There are two graph-facing nodes in this directory.

`explain_itinerary.py`
runs after Planner when planner output exists but copy/detail enrichment has not
been applied. It enriches itinerary details, builds safe summaries, optionally
calls the planner-copy LLM composer, and writes the updated `planner_output` back
to `state.planner`.

`node.py`
runs at the end or when clarification is needed. It adapts graph state into
`ResponsePackagerInput` and writes `state.response`.

`agent.py`
decides final response status:

- `modification_pending` when an initial itinerary draft is ready for user edits
- `END_WAIT_USER` when clarification is present
- `completed` after the user confirms the itinerary

It delegates API response shape construction to `packager.py`.

`packager.py`
owns the public response schema: destination, itinerary, explainability,
festival date verifications, links, and optional clarification.

`tools.py`
defines runtime injection for itinerary explanation: planner-copy runtime,
DynamoDB lookup, and schema retry limit.

## File Map

`contracts.py`
defines response packager input and output dataclasses.

`itinerary_explanation_mapping.py`
maps planner itinerary items into safe explanation inputs, enriches details, and
builds fallback explanation audits.

`planner_copy_composer.py`
owns LLM planner-copy generation, schema repair/retry, and fallback copy.

`explain_itinerary.py`
is the stateful node that applies the mapping and composer to planner output.

`packager.py`
is the final API response builder.

## State Contract

`explain_itinerary.py` reads:

- `state.planner.planner_output`
- selected city from `state.city_select.city_selection_result`
- query fields from `state.intent.city_select_input`
- optional `state.itinerary_explanation_runtime`

It writes:

- enriched `state.planner.planner_output`
- updated planner validation fields

`node.py` reads:

- `state.request` or fallback `intent.city_select_input`
- `state.planner.planner_output`
- `state.city_select.city_selection_result.selected_city`
- `state.festival_gate.verified_festival_cities`
- any clarification from `festival_gate` or existing response state

It writes:

- `state.response.response_status`
- `state.response.response_payload`
- `state.response.clarification`

## Clarification Behavior

Any clarification payload causes `END_WAIT_USER`. The public payload keeps the
normal response fields and adds `clarification` in camelCase. This allows clients
to preserve the V1-like response surface while handling V2 clarification.

## Change Guide

Change final API response shape in `packager.py`.

Change graph state extraction in `node.py`.

Change explanation/detail enrichment in `explain_itinerary.py` and
`itinerary_explanation_mapping.py`.

Change LLM copy generation behavior in `planner_copy_composer.py`.

Change runtime injection in `tools.py`.

## Tests

Relevant tests live under `tests/v2`:

- response clarification packaging
- response packager node tests
- planner copy/explanation tests
- graph routing tests that verify `explain_itinerary` precedes final packaging
