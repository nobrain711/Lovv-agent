# Profile Agent

Profile applies saved user preference weights to the active request themes. It is
currently a deterministic state node; a future profile service or LLM-backed
profile agent should preserve the same output contract.

## Runtime Flow

`node.py`
is the graph-facing implementation.

It reads:

- `state.intent.city_select_input`
- optional `state.profile.lovv_user_profile`
- optional `state.profile.mock_profile`
- optional `state.profile.profile_record.lovv_user_profile`

It writes:

- updated `state.intent.city_select_input.theme_weights` when the profile is active
- `state.profile.saved_trip_count`
- `state.profile.profile_theme_weights`
- `state.profile.effective_theme_weights`
- `state.profile.applied_persona_id`
- `state.profile.audit`

`manager.py`
is reserved for profile write rules, aggregate weights, and fallback triggers.

## Weight Policy

The weight math lives in `lovv_agent_v2.models.profile`, not inside this
directory. This node only applies the computed result to state.

The profile policy includes a hard activation gate: saved trip counts below the
configured threshold should keep effective theme weights neutral.

## State Contract

Profile must run after Intent because it needs normalized active themes.

Profile should not choose cities, festivals, or itinerary places. It only adds
theme weighting information for downstream ranking and planning.

## Change Guide

Change graph/state adaptation in `node.py`.

Change profile math in `lovv_agent_v2.models.profile`.

Add persistence or external profile loading in `manager.py` when that runtime is
introduced.
