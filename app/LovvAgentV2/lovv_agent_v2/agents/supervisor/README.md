# Supervisor

Supervisor is the central router for the V2 LangGraph application. It does not
perform domain work. It inspects state and decides the next node.

## Runtime Flow

`router.py`
is the graph-facing implementation.

`supervisor_node`
returns:

- `routing.next_node`
- `routing.completed_groups`
- `routing.needs_clarification`
- `routing.clarification_reason_code`

`route_next_action`
is the conditional-edge helper used by tests and graph wiring.

`dispatcher.py`
is reserved for future intent mapping, checkpointer validation, and session
avoid-flag logic.

## Routing Order

The parent graph starts at Supervisor and returns to Supervisor after every
domain node.

Current routing order:

1. End if response payload already exists.
2. Send clarification state to Response Packager.
3. Run Profile when profile audit is missing.
4. Run Festival Verifier unless festival mode is excluded.
5. Send terminal City Select failures to Response Packager.
6. Run City Select when no selected city exists.
7. Run Planner when no planner output exists.
8. Run Explain Itinerary when planner copy/detail enrichment is missing.
9. Run Response Packager.

## Festival Bypass

When `include_festivals` is false in either `state.request` or
`state.intent.city_select_input`, Supervisor treats `festival_gate` as complete
and routes directly from Profile to City Select.

## State Checks

Supervisor intentionally uses lightweight presence checks instead of validating
full domain schemas. Schema validation belongs to the domain nodes.

Important checks:

- profile is complete when `state.profile.audit` exists
- festival gate is complete when `state.festival_gate.result` or `audit` exists
- city select is complete when `city_selection_result` or terminal `status`
  exists
- planner is complete when `state.planner.planner_output` exists
- response is complete when `state.response.response_payload` exists

## Change Guide

Change graph routing policy in `router.py`.

Add future dispatch/checkpoint behavior in `dispatcher.py`.

Keep domain-specific validation out of Supervisor; add it to the target agent
node instead.

## Tests

Relevant tests live under `tests/v2`:

- supervisor graph tests
- graph routing tests
- smoke runner tests that exercise full node order
