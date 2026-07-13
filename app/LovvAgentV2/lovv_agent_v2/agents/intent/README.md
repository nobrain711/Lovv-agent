# Intent Agent

Intent is currently a normalization node, not the final LLM intent agent. It
accepts either prebuilt mock intent state or a request payload, normalizes it
into `CitySelectInput`, enriches city identity, and stores the normalized payload
under `state.intent.city_select_input`.

## Runtime Flow

`node.py`
is the graph-facing implementation.

It reads:

- existing `state.intent.city_select_input`
- fallback `state.intent.intent_output`
- fallback `state.request`

It writes:

- normalized `state.intent.city_select_input`
- `state.intent.cleaned_raw_query`
- `state.intent.soft_preference_query`
- `state.intent.unsupported_conditions`

`parser.py`
is reserved for the future primary parser.

`modify_parser.py`
is reserved for follow-up or edit intent parsing.

`validator.py`
is reserved for intent validation rules.

## Current Boundary

This directory should not own city identity lookup policy beyond calling
`enrich_city_select_identity`. Frontend-provided `destination_id` is expected to
already use the backend city ID format.

Transport preference and congestion preference are request or raw-query derived
fields and are passed through as part of `city_select_input`.

## Future Agent Contract

When the real Intent Agent replaces the mock path, it should produce the same
normalized `city_select_input` fields consumed by Profile, Festival Verifier,
City Select, and Planner. That keeps downstream nodes independent from whether
intent came from a mock file, request payload, or LLM parser.

## Change Guide

Change state normalization in `node.py`.

Add real parsing logic to `parser.py` and `modify_parser.py`.

Add validation that is independent of graph state in `validator.py`.

Keep downstream contract compatibility by validating against `CitySelectInput`.
