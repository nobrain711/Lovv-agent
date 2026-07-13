# Festival Verifier Agent

Festival Verifier is the optional festival gate between Profile and City Select.
It runs only when the request keeps `include_festivals` enabled. When festivals
are disabled, the supervisor can bypass this agent and City Select can run
directly.

## Runtime Flow

`node.py`
is the graph-facing adapter. It reads `intent.city_select_input`, optional
preloaded festival candidates, and city key fields from state.

`agent.py`
decides how to verify festivals:

- skip and emit audit-only gate when `include_festivals` is false
- evaluate preloaded candidates when present
- otherwise call DynamoDB festival lookup through `tools.py`

`verifier.py`
builds the actual festival gate result from candidate payloads.

`gate_result.py`
defines the normalized gate result and candidate wrapper used by the verifier.

`date_policy.py`
derives `confirmed`, `tentative`, `outdated`, `unknown`, or `skipped` from month
and optional date fields.

`clarification_options.py`
builds user clarification choices for no confirmed festival, tentative-only
festival data, and anchored-city conflicts.

`tools.py`
builds the DynamoDB lookup runtime.

`contracts.py`
defines graph-facing input and output dataclasses.

## State Contract

Input is expected at:

- `state.intent.city_select_input`
- optional `state.festival_gate.candidates`
- optional `state.request.festival_candidates`

Output is written to `state.festival_gate`:

- `result`
- `allowed_city_ids`
- `verified_festival_cities`
- `clarification`
- `audit`

City Select consumes `allowed_city_ids` when festival mode is active. Response
Packager consumes `clarification` and `verified_festival_cities`.

## DynamoDB Identity Notes

The verifier preserves DDB identity for diagnostics, but DDB PK is not used as an
S3 Vector metadata filter. City filtering for vector search should use city IDs
or allowed-city lists.

Festival table records may use a city PK shape like `CITY#...`, while city IDs
can use a separate front/backend identity such as `KR-...`. Preserve both when
available, but only city ID should drive downstream city filtering.

## Change Guide

Change festival date acceptance policy in `date_policy.py`.

Change gate status and output validation in `gate_result.py`.

Change clarification copy/options in `clarification_options.py`.

Change DynamoDB lookup integration in `tools.py` or `agent.py`.

Change state wiring only in `node.py`.

## Tests

Relevant tests live under `tests/v2` and should cover:

- confirmed festival gate
- tentative festival clarification
- anchored-city conflict
- festival-disabled supervisor bypass
- response packaging of clarification payloads
