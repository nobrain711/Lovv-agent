from __future__ import annotations

"""Retrieval Node (S3 vector search + Slot-based re-retrieval)."""

import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any
from concurrent.futures import ThreadPoolExecutor

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from lovv_agent_v2.infra.config import RuntimeConfig, SearchBudgetSettings
from lovv_agent_v2.models.schemas import SchemaValidationError, CitySelectInput, CitySelectResult
from lovv_agent_v2.infra.adapters.embeddings import BedrockEmbeddingAdapter
from lovv_agent_v2.infra.aws_clients import AwsClientFactory, AwsClientProvider, create_boto3_client_factory
from lovv_agent_v2.infra.dynamo_lookup import DynamoLookupTool
from lovv_agent_v2.infra.repositories.dynamodb import DynamoDbRepository
from lovv_agent_v2.infra.repositories.s3_vectors import S3VectorRepository, extract_vector_records
from lovv_agent_v2.common.telemetry import sanitize_text

_TRACER = trace.get_tracer("lovv_agent_v2.agents.city_select.retrieval_node")

TOOL_NAME = "DestinationSearchTool"

RESPONSIBILITY = "Search and normalize S3 Vector attraction evidence."

CITY_DISCOVERY_MODE = "city_discovery"
ANCHORED_PLACE_SEARCH_MODE = "anchored_place_search"
FESTIVAL_SEEDED_CITY_DISCOVERY_MODE = "festival_seeded_city_discovery"
ATTRACTION_ENTITY_TYPE = "attraction"
DEFAULT_RETURN_DISTANCE = True
DEFAULT_RETURN_METADATA = True
GOURMET_EXTERNAL_THEME_LABELS = frozenset(
    {
        "food_local",
        "미식",
        "미식·노포",
        "미식/노포",
    },
)
FESTIVAL_EXCLUDED_THEME_LABELS = frozenset(
    {
        "festival",
        "festival_event",
        "event",
        "축제",
        "축제·이벤트",
        "축제/이벤트",
    },
)
PLACE_SEARCH_EXCLUDED_THEME_LABELS = (
    GOURMET_EXTERNAL_THEME_LABELS | FESTIVAL_EXCLUDED_THEME_LABELS
)
EXTERNAL_LINK_THEME_LABELS = GOURMET_EXTERNAL_THEME_LABELS
FESTIVAL_THEME_MARKERS = FESTIVAL_EXCLUDED_THEME_LABELS
# vector row는 chunk로 쪼개질 수 있으므로 deduplication과 city grouping 전에
# chunk key를 canonical place id로 되돌린다.
_CHUNK_SUFFIX_PATTERN = re.compile(
    r"(?i)(?:::|#|/|_|-)?chunk(?:[-_:#/])?\d+$",
)
CITY_KEY_ALIASES = {
    "CITY#GOSEONG": "CITY#GOSEONG-GANGWON",
}


@dataclass(frozen=True, slots=True)
class AttractionCandidate:
    """Normalized attraction candidate produced from an S3 Vector record."""

    key: str
    place_id: str
    distance: float
    entity_type: str
    city_id: str
    city_name_ko: str | None
    title: str
    theme_tags: tuple[str, ...]
    latitude: float | None
    longitude: float | None
    ddb_pk: str | None
    ddb_sk: str | None
    metadata: dict[str, Any]
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a serializable candidate payload."""

        return asdict(self)


@dataclass(frozen=True, slots=True)
class PrunedCityGroups:
    """City groups that survived searchable theme coverage checks."""

    survived_groups: dict[str, tuple[AttractionCandidate, ...]]
    eliminated_cities: tuple[str, ...]
    available_themes_by_city: dict[str, tuple[str, ...]] | None = None
    missing_themes_by_city: dict[str, tuple[str, ...]] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a serializable city pruning payload."""

        return {
            "survived_groups": {
                city_id: [candidate.to_dict() for candidate in candidates]
                for city_id, candidates in self.survived_groups.items()
            },
            "eliminated_cities": list(self.eliminated_cities),
            "available_themes_by_city": self.available_themes_by_city or {},
            "missing_themes_by_city": self.missing_themes_by_city or {},
        }


@dataclass(frozen=True, slots=True)
class DestinationSearchTool:
    """S3 Vector destination retrieval facade over an injected repository."""

    s3_vectors: S3VectorRepository
    search_budget: SearchBudgetSettings

    def search_candidates(
        self,
        query_vector: Sequence[float],
        *,
        city_id: str | None = None,
        ddb_pk: str | None = None,
        theme: str | None = None,
        theme_tags: Sequence[str] | None = None,
        top_k: int | None = None,
    ) -> tuple[AttractionCandidate, ...]:
        """Search attraction candidates and normalize the raw vector response."""

        search_theme = _resolve_place_search_theme(theme, theme_tags)
        if search_theme is not None and _is_excluded_place_search_theme(search_theme):
            # 미식과 축제 theme은 별도 flow에서 처리하므로
            # 관광지 vector retrieval로 조용히 넓히지 않는다.
            return ()

        request = build_attraction_search_request(
            query_vector=query_vector,
            city_id=city_id,
            ddb_pk=ddb_pk,
            theme=search_theme,
            top_k=top_k,
            search_budget=self.search_budget,
        )
        response = self.s3_vectors.query_vectors(request)
        return tuple(
            normalize_attraction_candidate(record)
            for record in extract_vector_records(response)
        )

    def prune_cities(
        self,
        candidates: Sequence[AttractionCandidate],
        searchable_place_themes: Sequence[str],
        *,
        allowed_city_ids: Sequence[str] | None = None,
    ) -> PrunedCityGroups:
        """Group candidates by city and apply searchable place theme coverage."""

        return prune_cities(
            candidates,
            searchable_place_themes,
            allowed_city_ids=allowed_city_ids,
        )


def build_attraction_search_request(
    *,
    query_vector: Sequence[float],
    city_id: str | None = None,
    ddb_pk: str | None = None,
    theme: str | None = None,
    theme_tags: Sequence[str] | None = None,
    top_k: int | None = None,
    search_budget: SearchBudgetSettings,
) -> dict[str, Any]:
    """Build an attraction-only S3 Vector search request."""

    request = {
        "queryVector": {"float32": _normalize_query_vector(query_vector)},
        "topK": _resolve_top_k(top_k, search_budget),
        "returnMetadata": DEFAULT_RETURN_METADATA,
        "returnDistance": DEFAULT_RETURN_DISTANCE,
    }
    metadata_filter = build_attraction_filter(
        city_id=city_id,
        ddb_pk=ddb_pk,
        theme=theme,
        theme_tags=theme_tags,
    )
    if metadata_filter is not None:
        request["filter"] = metadata_filter
    return request


def build_attraction_filter(
    *,
    city_id: str | None = None,
    ddb_pk: str | None = None,
    theme: str | None = None,
    theme_tags: Sequence[str] | None = None,
) -> dict[str, Any] | None:
    """Build the metadata filter for general attraction place search."""

    conditions: list[dict[str, Any]] = [
        {
            "entity_type": {"$eq": ATTRACTION_ENTITY_TYPE},
        },
    ]
    normalized_city_id = _optional_text(city_id, "city_id")
    if normalized_city_id is not None:
        conditions.append(
            {
                "city_id": {"$eq": normalized_city_id},
            },
        )
    _optional_text(ddb_pk, "ddb_pk")

    normalized_theme = _resolve_place_search_theme(theme, theme_tags)
    if normalized_theme is not None:
        if _is_excluded_place_search_theme(normalized_theme):
            raise SchemaValidationError(
                "theme is not searchable through S3 Vector place search",
            )
        conditions.append(
            {
                "theme_tags": {"$eq": normalized_theme},
            },
        )

    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}


def _allowed_city_pk(city_id: str) -> str:
    """이름 기반 city_id(KR-Gyeongju)를 vector ddb_pk(CITY#GYEONGJU 대문자)로 변환.

    앵커 destinationId는 이름 기반이라 신규 벡터의 숫자 city_id(KR-47-130)와 직접
    매칭이 안 되므로, candidate.ddb_pk(대문자)와 비교하기 위한 변환. 숫자 city_id
    (KR-51-720)면 CITY#51-720 같은 무의미 값이 나오지만, 그쪽은 city_id 직접 매칭으로
    처리되므로 무해하다.
    """

    prefix, separator, suffix = city_id.partition("-")
    name = suffix if separator and len(prefix) == 2 and prefix.isupper() else city_id
    return f"CITY#{name.upper()}"


def prune_cities(
    candidates: Sequence[AttractionCandidate],
    searchable_place_themes: Sequence[str],
    *,
    allowed_city_ids: Sequence[str] | None = None,
) -> PrunedCityGroups:
    """Apply city pool restriction and searchable theme AND gate."""

    required_themes = tuple(
        theme
        for theme in _normalize_string_sequence(
            searchable_place_themes,
            "searchable_place_themes",
        )
        if not _is_excluded_place_search_theme(theme)
    )
    allowed = (
        {cid.strip().upper() for cid in _normalize_string_sequence(allowed_city_ids, "allowed_city_ids")}
        if allowed_city_ids is not None
        else None
    )
    # 앵커(destinationId)는 이름 기반이라 숫자 vector city_id와 직접 안 맞는다. ddb_pk
    # (CITY#대문자)로도 매칭해 앵커 경로를 살린다. 숫자 city_id seed(축제 발견)는 city_id
    # 직접 매칭으로 그대로 통과한다.
    allowed_pks = (
        {_allowed_city_pk(cid) for cid in allowed} if allowed is not None else None
    )
    grouped: dict[str, list[AttractionCandidate]] = {}
    for candidate in candidates:
        city_key = _candidate_city_key(candidate)
        if city_key is None:
            continue
        if allowed is not None:
            ddb_pk = (candidate.ddb_pk or "").upper()
            cand_city_id_upper = (candidate.city_id or "").upper()
            if cand_city_id_upper not in allowed and ddb_pk not in allowed_pks:
                continue
        grouped.setdefault(city_key, []).append(candidate)

    survived: dict[str, tuple[AttractionCandidate, ...]] = {}
    eliminated: list[str] = []
    available_themes_by_city: dict[str, tuple[str, ...]] = {}
    missing_themes_by_city: dict[str, tuple[str, ...]] = {}

    for city_id, city_candidates in grouped.items():
        city_themes = {
            theme
            for candidate in city_candidates
            for theme in candidate.theme_tags
        }
        avail = tuple(theme for theme in required_themes if theme in city_themes)
        missing = tuple(theme for theme in required_themes if theme not in city_themes)

        available_themes_by_city[city_id] = avail
        missing_themes_by_city[city_id] = missing

        # 테마 일부만 가진 도시도 생존
        survived[city_id] = tuple(city_candidates)

    return PrunedCityGroups(
        survived_groups=survived,
        eliminated_cities=tuple(eliminated),
        available_themes_by_city=available_themes_by_city,
        missing_themes_by_city=missing_themes_by_city,
    )


def normalize_attraction_candidate(record: Mapping[str, Any]) -> AttractionCandidate:
    """Normalize one raw S3 Vector attraction record."""

    if not isinstance(record, Mapping):
        raise SchemaValidationError("attraction candidate record must be a mapping")
    key = _required_text(_first_present(record, "key", "id"), "key")
    metadata = _metadata(record)
    entity_type = _required_text(metadata.get("entity_type"), "metadata.entity_type")
    if entity_type != ATTRACTION_ENTITY_TYPE:
        raise SchemaValidationError("metadata.entity_type must be attraction")

    return AttractionCandidate(
        key=key,
        place_id=_normalize_place_id(key=key, metadata=metadata),
        distance=_numeric(_first_present(record, "distance", "score"), "distance"),
        entity_type=entity_type,
        city_id=_required_text(metadata.get("city_id"), "metadata.city_id"),
        city_name_ko=_optional_text(
            metadata.get("city_name_ko"),
            "metadata.city_name_ko",
        ),
        title=_required_text(metadata.get("title"), "metadata.title"),
        theme_tags=_normalize_string_sequence(
            metadata.get("theme_tags"),
            "metadata.theme_tags",
        ),
        latitude=_optional_numeric(metadata.get("latitude"), "metadata.latitude"),
        longitude=_optional_numeric(metadata.get("longitude"), "metadata.longitude"),
        ddb_pk=_optional_text(metadata.get("ddb_pk"), "metadata.ddb_pk"),
        ddb_sk=_optional_text(metadata.get("ddb_sk"), "metadata.ddb_sk"),
        metadata=dict(metadata),
    )


def _normalize_place_id(*, key: str, metadata: Mapping[str, Any]) -> str:
    """Return metadata place id, or strip a chunk suffix from the vector key."""

    metadata_place_id = _optional_text(metadata.get("place_id"), "metadata.place_id")
    if metadata_place_id is not None:
        return metadata_place_id
    hash_parts = key.split("#")
    if len(hash_parts) >= 3 and hash_parts[-1].isdigit():
        return "#".join(hash_parts[:-1])
    normalized = _CHUNK_SUFFIX_PATTERN.sub("", key).strip()
    if not normalized:
        raise SchemaValidationError("place_id could not be normalized from key")
    return normalized


def _candidate_city_key(candidate: AttractionCandidate) -> str | None:
    """Return the grouping city key normalized as a canonical city key."""

    if candidate.ddb_pk:
        normalized = candidate.ddb_pk.strip().upper()
        return CITY_KEY_ALIASES.get(normalized, normalized)
    if candidate.city_id:
        return candidate.city_id.strip().upper()
    if candidate.city_name_ko:
        return candidate.city_name_ko.strip()
    return None

def _metadata(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return copied vector metadata."""

    value = record.get("metadata", {})
    if not isinstance(value, Mapping):
        raise SchemaValidationError("attraction candidate metadata must be a mapping")
    return dict(value)


def _first_present(record: Mapping[str, Any], *field_names: str) -> Any:
    """Return the first present field value from a raw record."""

    for field_name in field_names:
        if field_name in record:
            return record[field_name]
    joined = " or ".join(field_names)
    raise SchemaValidationError(f"missing required field: {joined}")


def _resolve_top_k(top_k: int | None, search_budget: SearchBudgetSettings) -> int:
    """Use call-level top K or fall back to injected runtime budget."""

    selected = (
        search_budget.per_theme_attraction_top_k
        if top_k is None
        else top_k
    )
    if isinstance(selected, bool) or not isinstance(selected, int) or selected <= 0:
        raise SchemaValidationError("top_k must be a positive integer")
    return selected


def _normalize_query_vector(query_vector: Sequence[float]) -> list[float]:
    """Validate and copy the embedding vector used for search."""

    if isinstance(query_vector, (str, bytes)) or not isinstance(query_vector, Sequence):
        raise SchemaValidationError("query_vector must be a numeric sequence")
    if not query_vector:
        raise SchemaValidationError("query_vector must not be empty")
    normalized: list[float] = []
    for value in query_vector:
        normalized.append(_numeric(value, "query_vector"))
    return normalized


def _resolve_place_search_theme(
    theme: str | None,
    theme_tags: Sequence[str] | None,
) -> str | None:
    """Resolve the single active theme used by one S3 Vector search call."""

    merged: list[str] = []
    normalized_theme = _optional_text(theme, "theme")
    if normalized_theme is not None:
        merged.append(normalized_theme)
    if theme_tags is not None:
        merged.extend(_normalize_string_sequence(theme_tags, "theme_tags"))
    deduped: list[str] = []
    seen: set[str] = set()
    for item in merged:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    if len(deduped) > 1:
        raise SchemaValidationError(
            "search_candidates accepts one active theme per S3 Vector query",
        )
    return deduped[0] if deduped else None


def _is_excluded_place_search_theme(theme: str) -> bool:
    """Return whether a theme must not trigger attraction vector search."""

    return theme in PLACE_SEARCH_EXCLUDED_THEME_LABELS


def _normalize_string_sequence(value: Any, field_name: str) -> tuple[str, ...]:
    """Validate a string sequence."""

    if value is None:
        return ()
    if isinstance(value, str):
        return (_required_text(value, field_name),)
    if not isinstance(value, (list, tuple)):
        raise SchemaValidationError(f"{field_name} must be a string sequence")
    return tuple(_required_text(item, field_name) for item in value)


def _required_text(value: Any, field_name: str) -> str:
    """Validate a non-empty text value."""

    if not isinstance(value, str):
        raise SchemaValidationError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise SchemaValidationError(f"{field_name} must be a non-empty string")
    return normalized


def _optional_text(value: Any, field_name: str) -> str | None:
    """Validate optional text and normalize blanks to ``None``."""

    if value is None:
        return None
    return _required_text(value, field_name)


def _numeric(value: Any, field_name: str) -> float:
    """Validate a numeric value without accepting booleans."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SchemaValidationError(f"{field_name} must be numeric")
    return float(value)


def _optional_numeric(value: Any, field_name: str) -> float | None:
    """Validate optional numeric metadata."""

    if value is None:
        return None
    return _numeric(value, field_name)


__all__ = [
    "ATTRACTION_ENTITY_TYPE",
    "DEFAULT_RETURN_DISTANCE",
    "DEFAULT_RETURN_METADATA",
    "GOURMET_EXTERNAL_THEME_LABELS",
    "PLACE_SEARCH_EXCLUDED_THEME_LABELS",
    "RESPONSIBILITY",
    "TOOL_NAME",
    "AttractionCandidate",
    "DestinationSearchTool",
    "FESTIVAL_EXCLUDED_THEME_LABELS",
    "PrunedCityGroups",
    "build_attraction_filter",
    "build_attraction_search_request",
    "normalize_attraction_candidate",
    "prune_cities",
]

# ==================== Candidate Evidence Retrieval Parts ====================

@dataclass(frozen=True, slots=True)
class CandidateThemeSplit:
    """Theme groups used by Candidate Evidence retrieval and downstream Planner.

    ``active_required_themes`` keeps user-selected travel themes that still
    matter to the recommendation. ``searchable_place_themes`` is the subset that
    can be used for attraction vector retrieval and scoring. ``external_link``
    themes are carried forward as selected-city CTA requirements instead of
    being searched in the attraction index.
    """

    active_required_themes: tuple[str, ...]
    searchable_place_themes: tuple[str, ...]
    external_link_themes: tuple[str, ...]
    ignored_theme_markers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CitySelectContext:
    """Resolved Candidate Evidence entry context for one graph run."""

    candidate_input: CitySelectInput
    mode: str
    theme_split: CandidateThemeSplit
    include_festivals: bool



def prepare_city_select_context(
    candidate_input: CitySelectInput | Mapping[str, Any],
) -> CitySelectContext:
    normalized_input = ensure_city_select_input(candidate_input)
    mode = resolve_city_select_mode(normalized_input)
    theme_split = split_candidate_themes(normalized_input.active_required_themes)

    return CitySelectContext(
        candidate_input=normalized_input,
        mode=mode,
        theme_split=theme_split,
        include_festivals=normalized_input.include_festivals,
    )



def ensure_city_select_input(
    candidate_input: CitySelectInput | Mapping[str, Any],
) -> CitySelectInput:
    """Accept schema instances or mappings at the node boundary."""

    if isinstance(candidate_input, CitySelectInput):
        return candidate_input
    if isinstance(candidate_input, Mapping):
        return CitySelectInput.from_mapping(candidate_input)
    raise SchemaValidationError("city_select_input must be a schema or mapping")



def resolve_city_select_mode(candidate_input: CitySelectInput) -> str:
    """Resolve execution mode from ``destinationId`` and ``includeFestivals``.

    A fixed destination always selects anchored search. ``includeFestivals`` is
    still preserved on the context so Task 6.3 can run the fixed-city festival
    lookup before Planner consumes the package.
    """

    if candidate_input.destination_id is not None:
        return ANCHORED_PLACE_SEARCH_MODE
    if candidate_input.include_festivals:
        return FESTIVAL_SEEDED_CITY_DISCOVERY_MODE
    return CITY_DISCOVERY_MODE



def split_candidate_themes(themes: Sequence[str]) -> CandidateThemeSplit:
    """Split active travel themes into searchable and external-link groups."""

    active_required_themes: list[str] = []
    searchable_place_themes: list[str] = []
    external_link_themes: list[str] = []
    ignored_theme_markers: list[str] = []

    for theme in _unique_theme_labels(themes):
        if theme in FESTIVAL_THEME_MARKERS:
            ignored_theme_markers.append(theme)
            continue
        active_required_themes.append(theme)
        if theme in EXTERNAL_LINK_THEME_LABELS:
            external_link_themes.append(theme)
        else:
            searchable_place_themes.append(theme)

    return CandidateThemeSplit(
        active_required_themes=tuple(active_required_themes),
        searchable_place_themes=tuple(searchable_place_themes),
        external_link_themes=tuple(external_link_themes),
        ignored_theme_markers=tuple(ignored_theme_markers),
    )



def _unique_theme_labels(themes: Sequence[str]) -> tuple[str, ...]:
    """Return stable, stripped theme labels without duplicates."""

    if isinstance(themes, str) or not isinstance(themes, Sequence):
        raise SchemaValidationError("active_required_themes must be a sequence")

    unique_themes: list[str] = []
    for raw_theme in themes:
        if not isinstance(raw_theme, str):
            raise SchemaValidationError("active_required_themes must contain strings")
        theme = raw_theme.strip()
        if not theme:
            raise SchemaValidationError("active_required_themes cannot contain blanks")
        if theme not in unique_themes:
            unique_themes.append(theme)
    return tuple(unique_themes)



def _retrieve_by_theme(
    destination_search: Any,
    *,
    query_vector: Sequence[float],
    themes: Sequence[str],
    city_id: str | None,
    ddb_pk: str | None = None,
) -> tuple[AttractionCandidate, ...]:
    """Call attraction retrieval once per searchable theme in parallel using ThreadPoolExecutor."""

    all_theme_candidates: dict[str, list[AttractionCandidate]] = {}

    with ThreadPoolExecutor(max_workers=max(1, len(themes))) as executor:
        raw_futures = {
            executor.submit(
                destination_search.search_candidates,
                query_vector,
                city_id=city_id,
                ddb_pk=ddb_pk,
                theme=theme,
            ): theme
            for theme in themes
        }

        for future, theme in raw_futures.items():
            all_theme_candidates[theme] = list(future.result())

    candidates: list[AttractionCandidate] = []
    for theme in themes:
        candidates.extend(all_theme_candidates.get(theme, []))
        
    return tuple(candidates)



def _merge_duplicate_candidates(
    candidates: Sequence[AttractionCandidate],
) -> tuple[AttractionCandidate, ...]:
    """Merge duplicate vector hits by stable ``place_id``."""

    by_place_id: dict[str, AttractionCandidate] = {}
    for candidate in candidates:
        previous = by_place_id.get(candidate.place_id)
        if previous is None or candidate.distance < previous.distance:
            by_place_id[candidate.place_id] = candidate
    return tuple(by_place_id.values())



def _package_failure(
    context: CitySelectContext,
    *,
    status: str,
    failure_signal: str,
    failure_signals: Sequence[str] | None = None,
    needs_clarification: bool,
    clarifying_question: str | None = None,
    retrieval_audit: Mapping[str, Any] | None = None,
) -> CitySelectResult:
    """Build a valid failure package at the Candidate Evidence boundary."""

    return CitySelectResult(
        status=status,
        failure_signals=tuple(failure_signals or (failure_signal,)),
        needs_clarification=needs_clarification,
        clarifying_question=clarifying_question,
        mode=context.mode,
        city_anchor=None,
        festival_candidates=(),
        selected_festival_candidates=(),
        festival_seed_audit={},
        retrieval_audit=dict(retrieval_audit or {}),
        candidate_counts={},
        fallback_audit={
            "planner_consumable": False,
            "failure_signal": failure_signal,
            "festival_seed_applied": False,
        },
    )



def _allowed_city_ids(
    *,
    context: CitySelectContext,
    allowed_city_ids: Sequence[str] | None,
) -> tuple[str, ...] | None:
    """Return the city pool restriction for prune/scoring."""

    if allowed_city_ids is not None:
        normalized = tuple(dict.fromkeys(allowed_city_ids))
        return normalized or None
    if context.candidate_input.destination_id is not None:
        return (context.candidate_input.destination_id,)
    return None


def _retrieval_audit(
    *,
    context: CitySelectContext,
    retrieved_count: int,
    merged_count: int,
    survived_city_count: int,
    eliminated_cities: Sequence[str],
) -> dict[str, Any]:
    """Build compact retrieval audit fields for review/debug."""

    return {
        "mode": context.mode,
        "searchable_place_themes": list(context.theme_split.searchable_place_themes),
        "external_link_themes": list(context.theme_split.external_link_themes),
        "fixed_city_id": context.candidate_input.destination_id,
        "retrieved_candidate_count": retrieved_count,
        "merged_candidate_count": merged_count,
        "survived_city_count": survived_city_count,
        "eliminated_cities": list(eliminated_cities),
    }


def _build_city_select_runtime_tools(
    config: RuntimeConfig,
    client_factory: AwsClientFactory,
) -> tuple[DestinationSearchTool, DynamoLookupTool, BedrockEmbeddingAdapter]:
    provider = AwsClientProvider.from_factory(
        client_factory,
        config=config,
    )
    runtime_clients = provider.create_runtime_clients()
    destination_search = DestinationSearchTool(
        s3_vectors=S3VectorRepository(
            client=runtime_clients.s3_vectors,
            settings=config.s3_vectors,
        ),
        search_budget=config.search_budget,
    )
    dynamo_lookup = DynamoLookupTool(
        dynamodb=DynamoDbRepository(
            client=runtime_clients.dynamodb,
            settings=config.dynamodb,
        ),
        search_budget=config.search_budget,
    )
    embedding_adapter = BedrockEmbeddingAdapter(
        client=runtime_clients.bedrock_runtime,
        model_id=_required_embedding_model_id(config.embeddings.model_id),
    )
    return destination_search, dynamo_lookup, embedding_adapter


def _city_select_failure_state(result: CitySelectResult) -> dict[str, Any]:
    return {
        "city_selection_result": None,
        "status": result.status,
        "clarification": None,
        "retrieval_audit": dict(result.retrieval_audit),
        "scoring_audit": {},
        "failure_signals": tuple(result.failure_signals),
        "fallback_audit": dict(result.fallback_audit),
        "clarifying_question": result.clarifying_question,
    }


def _required_embedding_model_id(model_id: str | None) -> str:
    if model_id is None:
        raise SchemaValidationError("LOVV_EMBEDDING_MODEL_ID is required for city_select")
    return model_id


def _embedding_query_text(context: CitySelectContext) -> str:
    query = context.candidate_input.cleaned_raw_query.strip()
    if not query:
        raise SchemaValidationError("cleaned_raw_query is required for city_select embedding")
    return query



from lovv_agent_v2.core.state import UnifiedAgentState

def retrieval_node(state: UnifiedAgentState) -> dict:
    """Retrieve tourist spots from S3 Vector DB and prune them."""
    intent = state.get("intent", {}) if isinstance(state, dict) else getattr(state, "intent", None)
    
    if isinstance(intent, dict):
        candidate_input = intent.get("city_select_input")
    else:
        candidate_input = getattr(intent, "city_select_input", None)

    if not candidate_input:
        raise ValueError("city_select_input is required in state['intent']")

    context = prepare_city_select_context(candidate_input)
    allowed_city_ids = _festival_gate_allowed_city_ids(state)
    if context.include_festivals and allowed_city_ids is None:
        fail_pkg = _package_failure(
            context,
            status="error",
            failure_signal="missing_festival_gate_allowed_city_ids",
            needs_clarification=False,
            retrieval_audit={
                "festival_gate_required": True,
                "reason": "city_select_requires_festival_gate_allowed_city_ids",
            },
        )
        return {"city_select": _city_select_failure_state(fail_pkg)}

    config = RuntimeConfig.from_env()
    client_factory = create_boto3_client_factory(profile_name=config.aws.profile_name)
    destination_search, _, embedding_adapter = _build_city_select_runtime_tools(
        config,
        client_factory,
    )
    query_vector = embedding_adapter.embed_query(_embedding_query_text(context))

    festival_seed_result = None
    if not context.theme_split.searchable_place_themes:
        fail_pkg = _package_failure(
            context,
            status="no_candidate",
            failure_signal="no_searchable_place_theme",
            needs_clarification=True,
            clarifying_question="현재 조건에서는 검색 가능한 관광 테마가 없습니다.",
        )
        return {"city_select": _city_select_failure_state(fail_pkg)}

    anchor_ddb_pk = _allowed_city_pk(context.candidate_input.destination_id) if context.candidate_input.destination_id else None
    retrieved = _retrieve_by_theme(
        destination_search,
        query_vector=query_vector,
        themes=context.theme_split.searchable_place_themes,
        city_id=None,
        ddb_pk=anchor_ddb_pk,
    )
    merged_candidates = _merge_duplicate_candidates(retrieved)
    allowed = _allowed_city_ids(context=context, allowed_city_ids=allowed_city_ids)
    pruned_groups = destination_search.prune_cities(
        merged_candidates,
        context.theme_split.searchable_place_themes,
        allowed_city_ids=allowed,
    )

    return {
        "city_select": {
            "pruned_groups": pruned_groups,
            "festival_seed_result": festival_seed_result,
            "context": context,
            "retrieved_count": len(retrieved),
            "merged_count": len(merged_candidates),
            "survived_city_count": len(pruned_groups.survived_groups) if pruned_groups else 0,
            "eliminated_cities": tuple(pruned_groups.eliminated_cities) if pruned_groups else (),
        }
    }


def _festival_gate_allowed_city_ids(state: UnifiedAgentState) -> tuple[str, ...] | None:
    festival_gate = state.get("festival_gate", {}) if isinstance(state, dict) else {}
    if isinstance(festival_gate, Mapping):
        gate_allowed_city_ids = festival_gate.get("allowed_city_ids")
        if isinstance(gate_allowed_city_ids, Sequence) and not isinstance(
            gate_allowed_city_ids,
            (str, bytes),
        ):
            return tuple(str(city_id) for city_id in gate_allowed_city_ids)
    return None
