from __future__ import annotations

import csv
import hashlib
import json
import random
import statistics
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from lovv_agent_v2.common.subtypes import subtype_name

SOFT_WEIGHTS: tuple[float, ...] = (0.05, 0.10, 0.20, 0.30)


@dataclass(frozen=True, slots=True)
class ValidationConfig:
    input_dir: Path
    output_dir: Path
    top_n: int = 30
    judge_candidates_per_case: int = 10
    city_top_k: int = 5


@dataclass(frozen=True, slots=True)
class Candidate:
    case_id: str
    channel: str
    lane: str
    theme_filter: str | None
    rank: int
    place_id: str
    distance: float
    city_id: str | None
    city_name_ko: str | None
    title: str
    theme_tags: tuple[str, ...]
    subtype: str | None
    ddb_pk: str | None
    ddb_sk: str | None

    @property
    def city_key(self) -> str:
        return self.ddb_pk or self.city_id or self.city_name_ko or "unknown"


@dataclass(frozen=True, slots=True)
class CaseData:
    case_id: str
    raw_query: str
    soft_query: str
    themes: tuple[str, ...]
    raw_candidates: tuple[Candidate, ...]
    soft_candidates: tuple[Candidate, ...]
    raw_theme_candidates: tuple[Candidate, ...]
    soft_theme_candidates: tuple[Candidate, ...]

    @property
    def has_soft_query(self) -> bool:
        return bool(self.soft_query.strip())


@dataclass(frozen=True, slots=True)
class CityScore:
    case_id: str
    variant: str
    soft_weight: float
    rank: int
    city_key: str
    city_name_ko: str
    score: float
    semantic_relevance: float
    theme_coverage: float
    missing_theme_count: int
    missing_themes: tuple[str, ...]
    soft_alignment: float
    representative_seed_place_id: str
    representative_seed_title: str
    representative_seed_subtype: str
    representative_seed_subtype_name: str
    representative_seed_distance: float


def run_validation(config: ValidationConfig) -> None:
    cases = load_cases(config.input_dir, config.top_n)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    case_metrics = [_case_metrics(case) for case in cases]
    city_rows = _city_ablation_rows(cases, config.city_top_k)
    stability_rows = _stability_rows(cases, city_rows)
    soft_only = _soft_only_candidates(cases, config.judge_candidates_per_case)
    pairwise_tasks = _pairwise_tasks(cases, city_rows)

    _write_csv(config.output_dir / "case_metrics.csv", case_metrics)
    _write_json(config.output_dir / "summary_metrics.json", _summary(cases, case_metrics, stability_rows, config))
    _write_csv(config.output_dir / "soft_only_candidates_for_judge.csv", _soft_only_csv_rows(soft_only))
    _write_jsonl(config.output_dir / "soft_only_candidates_for_judge.jsonl", _soft_only_jsonl_rows(soft_only))
    _write_csv(config.output_dir / "city_ablation_topk.csv", [_city_row(score) for score in city_rows])
    _write_csv(config.output_dir / "ranking_stability.csv", stability_rows)
    _write_jsonl(config.output_dir / "pairwise_city_judge_tasks.jsonl", pairwise_tasks)
    judge_input, auto_ties = _pairwise_judge_inputs(pairwise_tasks)
    _write_jsonl(config.output_dir / "judge_input_sanitized.jsonl", judge_input)
    _write_jsonl(config.output_dir / "pairwise_auto_ties.jsonl", auto_ties)
    (config.output_dir / "soft_channel_validation_report.md").write_text(
        _report(cases, case_metrics, stability_rows, soft_only, pairwise_tasks, judge_input, auto_ties, config),
        encoding="utf-8",
    )


def load_cases(input_dir: Path, top_n: int) -> list[CaseData]:
    cases: list[CaseData] = []
    for path in sorted(input_dir.glob("*.json")):
        if path.name == "_summary.json":
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            continue
        query = _mapping(raw.get("query"))
        channels = _mapping(raw.get("channels"))
        case_id = _text(raw.get("case_id")) or path.stem
        themes = tuple(_text_list(query.get("themes")))
        case = CaseData(
            case_id=case_id,
            raw_query=_text(query.get("raw_query")),
            soft_query=_text(query.get("soft_query")),
            themes=themes,
            raw_candidates=tuple(_primary_candidates(case_id, "raw", channels, top_n)),
            soft_candidates=tuple(_primary_candidates(case_id, "soft", channels, top_n)),
            raw_theme_candidates=tuple(_theme_candidates(case_id, "raw", channels, top_n)),
            soft_theme_candidates=tuple(_theme_candidates(case_id, "soft", channels, top_n)),
        )
        if case.raw_candidates:
            cases.append(case)
    return cases


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _optional_text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _float(value: Any) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    return None


def _rank(value: Any) -> int:
    return int(value) if isinstance(value, int | float) else 0


def _primary_candidates(case_id: str, channel: str, channels: Mapping[str, Any], top_n: int) -> list[Candidate]:
    source = _mapping(channels.get(channel))
    union = _mapping(source.get("per_theme_union"))
    if union:
        return _ranked_candidates(case_id, channel, "per_theme_union", None, union, top_n)
    return _ranked_candidates(case_id, channel, "no_theme", None, _mapping(source.get("no_theme")), top_n)


def _theme_candidates(case_id: str, channel: str, channels: Mapping[str, Any], top_n: int) -> list[Candidate]:
    source = _mapping(channels.get(channel))
    per_theme = _mapping(source.get("per_theme"))
    candidates: list[Candidate] = []
    for theme, payload in per_theme.items():
        if isinstance(theme, str):
            candidates.extend(_ranked_candidates(case_id, channel, "per_theme", theme, _mapping(payload), top_n))
    if candidates:
        return candidates
    return _primary_candidates(case_id, channel, channels, top_n)


def _ranked_candidates(
    case_id: str,
    channel: str,
    lane: str,
    theme_filter: str | None,
    payload: Mapping[str, Any],
    top_n: int,
) -> list[Candidate]:
    ranked = payload.get("ranked")
    if not isinstance(ranked, list):
        return []
    candidates: list[Candidate] = []
    for item in ranked:
        data = _mapping(item)
        rank = _rank(data.get("rank"))
        distance = _float(data.get("distance"))
        place_id = _text(data.get("place_id"))
        if rank > top_n or distance is None or not place_id:
            continue
        candidates.append(
            Candidate(
                case_id=case_id,
                channel=channel,
                lane=lane,
                theme_filter=theme_filter,
                rank=rank,
                place_id=place_id,
                distance=distance,
                city_id=_optional_text(data.get("city_id")),
                city_name_ko=_optional_text(data.get("city_name_ko")),
                title=_text(data.get("title")),
                theme_tags=tuple(_text_list(data.get("theme_tags"))),
                subtype=_optional_text(data.get("subtype")),
                ddb_pk=_optional_text(data.get("ddb_pk")),
                ddb_sk=_optional_text(data.get("ddb_sk")),
            ),
        )
    return candidates


def _case_metrics(case: CaseData) -> dict[str, Any]:
    raw_places = {candidate.place_id for candidate in case.raw_candidates}
    soft_places = {candidate.place_id for candidate in case.soft_candidates}
    raw_cities = {candidate.city_key for candidate in case.raw_candidates}
    soft_cities = {candidate.city_key for candidate in case.soft_candidates}
    soft_only_places = soft_places - raw_places
    soft_only_distances = [c.distance for c in case.soft_candidates if c.place_id in soft_only_places]
    return {
        "case_id": case.case_id,
        "has_soft_query": case.has_soft_query,
        "theme_count": len(case.themes),
        "raw_place_count": len(raw_places),
        "soft_place_count": len(soft_places),
        "place_jaccard": _jaccard(raw_places, soft_places),
        "city_jaccard": _jaccard(raw_cities, soft_cities),
        "soft_only_place_count": len(soft_only_places),
        "soft_only_place_rate": _rate(len(soft_only_places), len(raw_places | soft_places)),
        "soft_only_city_count": len(soft_cities - raw_cities),
        "soft_only_city_rate": _rate(len(soft_cities - raw_cities), len(raw_cities | soft_cities)),
        "raw_distance_mean": _mean([c.distance for c in case.raw_candidates]),
        "raw_distance_median": _median([c.distance for c in case.raw_candidates]),
        "soft_distance_mean": _mean([c.distance for c in case.soft_candidates]),
        "soft_distance_median": _median([c.distance for c in case.soft_candidates]),
        "soft_only_distance_mean": _mean(soft_only_distances),
        "soft_only_distance_median": _median(soft_only_distances),
    }


def _city_ablation_rows(cases: Sequence[CaseData], city_top_k: int) -> list[CityScore]:
    rows: list[CityScore] = []
    for case in cases:
        raw_scores = _rank_cities(case, 0.0, city_top_k, "raw_only")
        rows.extend(raw_scores)
        for soft_weight in SOFT_WEIGHTS:
            rows.extend(_rank_cities(case, soft_weight, city_top_k, "raw_soft"))
    return rows


def _rank_cities(case: CaseData, soft_weight: float, city_top_k: int, variant: str) -> list[CityScore]:
    raw_by_city = _by_city(case.raw_theme_candidates)
    soft_by_city = _by_city(case.soft_theme_candidates)
    distances = [c.distance for c in case.raw_theme_candidates + case.soft_theme_candidates]
    min_distance = min(distances) if distances else 0.0
    max_distance = max(distances) if distances else 0.0
    scores: list[CityScore] = []
    for city_key, candidates in raw_by_city.items():
        semantic = max(_norm(c.distance, min_distance, max_distance) for c in candidates)
        theme_scores = _theme_scores(case.themes, candidates, min_distance, max_distance)
        missing = tuple(theme for theme in case.themes if theme not in theme_scores)
        coverage = _mean(list(theme_scores.values())) if case.themes else semantic
        missing_penalty = _rate(len(missing), len(case.themes))
        soft_alignment = _soft_alignment(soft_by_city.get(city_key, []), min_distance, max_distance)
        score = (0.60 * semantic) + (0.40 * coverage) - (0.30 * missing_penalty)
        if variant == "raw_soft":
            score += soft_weight * soft_alignment
        seed = min(candidates, key=lambda candidate: candidate.distance)
        scores.append(
            CityScore(
                case_id=case.case_id,
                variant=variant,
                soft_weight=soft_weight,
                rank=0,
                city_key=city_key,
                city_name_ko=seed.city_name_ko or city_key,
                score=round(score, 6),
                semantic_relevance=round(semantic, 6),
                theme_coverage=round(coverage, 6),
                missing_theme_count=len(missing),
                missing_themes=missing,
                soft_alignment=round(soft_alignment, 6),
                representative_seed_place_id=seed.place_id,
                representative_seed_title=seed.title,
                representative_seed_subtype=seed.subtype or "",
                representative_seed_subtype_name=subtype_name(seed.subtype),
                representative_seed_distance=seed.distance,
            ),
        )
    ordered = sorted(scores, key=lambda row: (-row.score, row.representative_seed_distance, row.city_key))
    return [replace(row, rank=rank) for rank, row in enumerate(ordered[:city_top_k], start=1)]


def _by_city(candidates: Sequence[Candidate]) -> dict[str, list[Candidate]]:
    grouped: dict[str, list[Candidate]] = defaultdict(list)
    for candidate in candidates:
        grouped[candidate.city_key].append(candidate)
    return dict(grouped)


def _theme_scores(themes: Sequence[str], candidates: Sequence[Candidate], min_distance: float, max_distance: float) -> dict[str, float]:
    scores: dict[str, float] = {}
    for theme in themes:
        theme_candidates = [c for c in candidates if c.theme_filter == theme or theme in c.theme_tags]
        if theme_candidates:
            scores[theme] = max(_norm(c.distance, min_distance, max_distance) for c in theme_candidates)
    return scores


def _soft_alignment(candidates: Sequence[Candidate], min_distance: float, max_distance: float) -> float:
    if not candidates:
        return 0.0
    return max(_norm(candidate.distance, min_distance, max_distance) for candidate in candidates)


def _stability_rows(cases: Sequence[CaseData], city_rows: Sequence[CityScore]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in cases:
        raw_top = [r for r in city_rows if r.case_id == case.case_id and r.variant == "raw_only"]
        for weight in SOFT_WEIGHTS:
            soft_top = [r for r in city_rows if r.case_id == case.case_id and r.variant == "raw_soft" and r.soft_weight == weight]
            rows.append({
                "case_id": case.case_id,
                "soft_weight": weight,
                "has_soft_query": case.has_soft_query,
                "top1_changed": bool(raw_top and soft_top and raw_top[0].city_key != soft_top[0].city_key),
                "top3_jaccard": _jaccard({r.city_key for r in raw_top[:3]}, {r.city_key for r in soft_top[:3]}),
            })
    return rows


def _soft_only_candidates(cases: Sequence[CaseData], per_case: int) -> list[tuple[CaseData, Candidate]]:
    rows: list[tuple[CaseData, Candidate]] = []
    for case in cases:
        raw_places = {candidate.place_id for candidate in case.raw_candidates}
        soft_only = sorted(
            [candidate for candidate in case.soft_candidates if candidate.place_id not in raw_places],
            key=lambda candidate: (candidate.distance, candidate.rank),
        )
        rows.extend((case, candidate) for candidate in soft_only[:per_case])
    return rows


def _pairwise_tasks(cases: Sequence[CaseData], city_rows: Sequence[CityScore]) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for case in cases:
        raw_top = [r for r in city_rows if r.case_id == case.case_id and r.variant == "raw_only"][:3]
        for weight in SOFT_WEIGHTS:
            soft_top = [r for r in city_rows if r.case_id == case.case_id and r.variant == "raw_soft" and r.soft_weight == weight][:3]
            if not raw_top or not soft_top:
                continue
            labels = ["raw_only", "raw_soft"]
            random.Random(_stable_seed(case.case_id, weight)).shuffle(labels)
            variants = {
                "raw_only": _variant_payload("A" if labels[0] == "raw_only" else "B", raw_top),
                "raw_soft": _variant_payload("A" if labels[0] == "raw_soft" else "B", soft_top),
            }
            tasks.append({
                "task_id": f"pairwise::{case.case_id}::soft_weight_{weight:.2f}",
                "case_id": case.case_id,
                "raw_query": case.raw_query,
                "soft_query": case.soft_query,
                "themes": list(case.themes),
                "variant_a": variants[labels[0]],
                "variant_b": variants[labels[1]],
                "hidden_mapping": {"A": labels[0], "B": labels[1]},
                "question": "사용자 요청에 더 적합한 도시 후보 묶음은 A인가 B인가?",
            })
    return tasks


def _stable_seed(case_id: str, weight: float) -> int:
    digest = hashlib.sha256(f"{case_id}:{weight:.2f}".encode("utf-8")).hexdigest()
    return int(digest[:12], 16)


def _variant_payload(label: str, rows: Sequence[CityScore]) -> dict[str, Any]:
    return {
        "label": label,
        "cities": [
            {
                "rank": row.rank,
                "city_name_ko": row.city_name_ko,
                "score": row.score,
                "representative_seed_title": row.representative_seed_title,
                "representative_seed_subtype": row.representative_seed_subtype,
                "representative_seed_subtype_name": row.representative_seed_subtype_name,
                "missing_themes": list(row.missing_themes),
            }
            for row in rows
        ],
    }


def _pairwise_judge_inputs(tasks: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    judge_input: list[dict[str, Any]] = []
    auto_ties: list[dict[str, Any]] = []
    for task in tasks:
        variant_a = _mapping(task.get("variant_a"))
        variant_b = _mapping(task.get("variant_b"))
        cities_a = _sanitized_cities(variant_a)
        cities_b = _sanitized_cities(variant_b)
        base = {
            "task_id": task.get("task_id"),
            "case_id": task.get("case_id"),
            "raw_query": task.get("raw_query"),
            "soft_query": task.get("soft_query"),
            "themes": task.get("themes"),
            "variant_a": {"label": "A", "cities": cities_a},
            "variant_b": {"label": "B", "cities": cities_b},
            "question": task.get("question"),
        }
        if cities_a == cities_b:
            auto_ties.append({**base, "auto_winner": "Tie", "auto_reason": "same_top3"})
        else:
            judge_input.append(base)
    return judge_input, auto_ties


def _sanitized_cities(variant: Mapping[str, Any]) -> list[dict[str, Any]]:
    cities = variant.get("cities")
    if not isinstance(cities, list):
        return []
    sanitized: list[dict[str, Any]] = []
    for city in cities:
        item = _mapping(city)
        sanitized.append({
            "rank": item.get("rank"),
            "city_name_ko": item.get("city_name_ko"),
            "representative_seed_title": item.get("representative_seed_title"),
            "representative_seed_subtype": item.get("representative_seed_subtype"),
            "representative_seed_subtype_name": item.get("representative_seed_subtype_name"),
            "missing_themes": item.get("missing_themes"),
        })
    return sanitized


def _soft_only_csv_rows(rows: Sequence[tuple[CaseData, Candidate]]) -> list[dict[str, Any]]:
    return [
        {
            "case_id": case.case_id,
            "raw_query": case.raw_query,
            "soft_query": case.soft_query,
            "themes": "|".join(case.themes),
            "place_id": candidate.place_id,
            "title": candidate.title,
            "city_id": candidate.city_id or "",
            "city_name_ko": candidate.city_name_ko or "",
            "theme_tags": "|".join(candidate.theme_tags),
            "subtype": candidate.subtype or "",
            "subtype_name": subtype_name(candidate.subtype),
            "distance": candidate.distance,
            "rank": candidate.rank,
            "judge_score": "",
            "judge_reason": "",
        }
        for case, candidate in rows
    ]


def _soft_only_jsonl_rows(rows: Sequence[tuple[CaseData, Candidate]]) -> list[dict[str, Any]]:
    return [
        {
            "task_id": f"soft_only::{case.case_id}::{candidate.place_id}",
            "case_id": case.case_id,
            "raw_query": case.raw_query,
            "soft_query": case.soft_query,
            "themes": list(case.themes),
            "candidate": {
                "place_id": candidate.place_id,
                "title": candidate.title,
                "city_id": candidate.city_id,
                "city_name_ko": candidate.city_name_ko,
                "theme_tags": list(candidate.theme_tags),
                "subtype": candidate.subtype,
                "subtype_name": subtype_name(candidate.subtype),
                "distance": candidate.distance,
                "rank": candidate.rank,
            },
            "question": "이 후보는 soft_query의 분위기/감성 조건에 얼마나 잘 맞는가? 1~5점으로 평가하라.",
        }
        for case, candidate in rows
    ]


def _city_row(row: CityScore) -> dict[str, Any]:
    return {
        "case_id": row.case_id,
        "variant": row.variant,
        "soft_weight": row.soft_weight,
        "rank": row.rank,
        "city_key": row.city_key,
        "city_name_ko": row.city_name_ko,
        "score": row.score,
        "semantic_relevance": row.semantic_relevance,
        "theme_coverage": row.theme_coverage,
        "missing_theme_count": row.missing_theme_count,
        "missing_themes": "|".join(row.missing_themes),
        "soft_alignment": row.soft_alignment,
        "representative_seed_place_id": row.representative_seed_place_id,
        "representative_seed_title": row.representative_seed_title,
        "representative_seed_subtype": row.representative_seed_subtype,
        "representative_seed_subtype_name": row.representative_seed_subtype_name,
        "representative_seed_distance": row.representative_seed_distance,
    }


def _summary(
    cases: Sequence[CaseData],
    case_metrics: Sequence[Mapping[str, Any]],
    stability_rows: Sequence[Mapping[str, Any]],
    config: ValidationConfig,
) -> dict[str, Any]:
    soft_cases = [case for case in cases if case.has_soft_query]
    return {
        "input_dir": str(config.input_dir),
        "output_dir": str(config.output_dir),
        "top_n": config.top_n,
        "case_count": len(cases),
        "soft_query_case_count": len(soft_cases),
        "empty_soft_query_case_count": len(cases) - len(soft_cases),
        "mean_place_jaccard": _metric_mean(case_metrics, "place_jaccard", soft_only=True),
        "median_place_jaccard": _metric_median(case_metrics, "place_jaccard", soft_only=True),
        "mean_city_jaccard": _metric_mean(case_metrics, "city_jaccard", soft_only=True),
        "mean_soft_only_place_rate": _metric_mean(case_metrics, "soft_only_place_rate", soft_only=True),
        "mean_soft_only_city_rate": _metric_mean(case_metrics, "soft_only_city_rate", soft_only=True),
        "top1_change_rate_by_weight": {
            f"{weight:.2f}": _change_rate(stability_rows, weight) for weight in SOFT_WEIGHTS
        },
        "mean_top3_jaccard_by_weight": {
            f"{weight:.2f}": _top3_mean(stability_rows, weight) for weight in SOFT_WEIGHTS
        },
    }


def _report(
    cases: Sequence[CaseData],
    case_metrics: Sequence[Mapping[str, Any]],
    stability_rows: Sequence[Mapping[str, Any]],
    soft_only: Sequence[tuple[CaseData, Candidate]],
    pairwise_tasks: Sequence[Mapping[str, Any]],
    judge_input: Sequence[Mapping[str, Any]],
    auto_ties: Sequence[Mapping[str, Any]],
    config: ValidationConfig,
) -> str:
    soft_count = sum(1 for case in cases if case.has_soft_query)
    place_jaccard = _metric_mean(case_metrics, "place_jaccard", soft_only=True)
    city_jaccard = _metric_mean(case_metrics, "city_jaccard", soft_only=True)
    soft_place_rate = _metric_mean(case_metrics, "soft_only_place_rate", soft_only=True)
    soft_city_rate = _metric_mean(case_metrics, "soft_only_city_rate", soft_only=True)
    raw_distance = _metric_mean(case_metrics, "raw_distance_mean", soft_only=True)
    soft_distance = _metric_mean(case_metrics, "soft_distance_mean", soft_only=True)
    top1_w010 = _change_rate(stability_rows, 0.10)
    top3_w010 = _top3_mean(stability_rows, 0.10)
    stability_table = "\n".join(
        f"| {weight:.2f} | {_change_rate(stability_rows, weight):.4f} | {_top3_mean(stability_rows, weight):.4f} |"
        for weight in SOFT_WEIGHTS
    )
    return f"""# Soft Query Channel 1차 검증 리포트

## 1. 데이터 개요
- 입력: `{config.input_dir}`
- 출력: `{config.output_dir}`
- case 수: {len(cases)}
- soft_query 존재 case 수: {soft_count}
- soft_query 빈 case 수: {len(cases) - soft_count}
- 사용 top_n: {config.top_n}

## 2. Retrieval Delta
- soft_query 존재 case 기준 평균 place Jaccard: **{place_jaccard:.4f}**
- soft_query 존재 case 기준 평균 city Jaccard: **{city_jaccard:.4f}**
- 평균 soft-only place 비율: **{soft_place_rate:.4f}**
- 평균 soft-only city 비율: **{soft_city_rate:.4f}**
- raw 평균 distance: **{raw_distance:.4f}**
- soft 평균 distance: **{soft_distance:.4f}**
- 해석: soft channel은 raw와 다른 후보군을 제공하지만, 이 수치는 후보 확장 효과만 보여주며 품질 개선을 직접 증명하지는 않는다.

## 3. Soft-only 후보 Judge 준비 결과
- 생성된 soft-only 후보 judge task 수: {len(soft_only)}
- case당 최대 후보 수: {config.judge_candidates_per_case}
- judge 입력 파일: `soft_only_candidates_for_judge.csv`, `soft_only_candidates_for_judge.jsonl`

## 4. Offline City Ranking Simulation
- 비교 방식: raw-only vs raw+soft, hard AND filtering 없음, candidate sufficiency 미사용
- soft_weight=0.10 기준 Top1 변경률: **{top1_w010:.4f}**
- soft_weight=0.10 기준 Top3 Jaccard 평균: **{top3_w010:.4f}**
- 전체 weight별 상세 결과는 `city_ablation_topk.csv`와 `ranking_stability.csv`에 기록했다.

| soft_weight | Top1 변경률 | Top3 Jaccard 평균 |
| ---: | ---: | ---: |
{stability_table}

## 5. Pairwise Judge Task
- 생성된 전체 pairwise task 수: {len(pairwise_tasks)}
- 자동 Tie 처리 task 수: {len(auto_ties)}
- 실제 judge 대상 task 수: {len(judge_input)}
- 내부 audit 파일: `pairwise_city_judge_tasks.jsonl`
- judge 입력 파일: `judge_input_sanitized.jsonl`
- 자동 Tie 파일: `pairwise_auto_ties.jsonl`
- judge 후 raw+soft win/loss rate를 계산해야 최종 scoring 반영 강도를 확정할 수 있다.

## 6. 1차 결론
- 현재 JSON 기준 soft channel은 raw와 충분히 다른 후보군을 제공한다.
- 현재 JSON만으로는 soft-only 후보가 실제 분위기/감성 의도에 맞는지, raw+soft 도시 묶음이 더 나은지 확정할 수 없다.
- 따라서 V2.0에서는 soft channel을 retrieval에는 유지하되 city_score에는 약한 보조 가점 또는 tie-break로만 반영하는 것이 안전하다.

## 7. 권고
- soft channel: 유지.
- scoring 반영 강도: strong factor가 아니라 `0.05~0.10` 수준의 약한 보조 가점 또는 동점 해소 신호로 제한.
- 추가 검증: `soft_only_candidates_for_judge.*`와 `pairwise_city_judge_tasks.jsonl`에 judge 결과를 채운 뒤 controlled pair 평가를 별도로 수행.

## 8. 제한
- 이번 검증은 저장된 retrieval JSON만 사용했으며 S3 Vector, Bedrock, OpenAI API를 호출하지 않았다.
- city key alias/canonicalization은 기존 JSON의 `ddb_pk or city_id or city_name_ko`를 그대로 사용했다.
- offline score는 운영용 확정 공식이 아니라 raw-only/raw+soft 비교용 ablation 공식이다.
"""


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fieldnames = list(rows[0].keys()) if rows else ["empty"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    lines = [json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    if not union:
        return 0.0
    return round(len(left & right) / len(union), 6)


def _rate(count: int, total: int) -> float:
    return round(count / max(1, total), 6)


def _mean(values: Sequence[float]) -> float:
    return round(statistics.fmean(values), 6) if values else 0.0


def _median(values: Sequence[float]) -> float:
    return round(statistics.median(values), 6) if values else 0.0


def _norm(distance: float, min_distance: float, max_distance: float) -> float:
    if max_distance == min_distance:
        return 1.0
    return 1.0 - ((distance - min_distance) / (max_distance - min_distance))


def _metric_values(rows: Sequence[Mapping[str, Any]], key: str, *, soft_only: bool) -> list[float]:
    values: list[float] = []
    for row in rows:
        if soft_only and not row.get("has_soft_query"):
            continue
        value = row.get(key)
        if isinstance(value, int | float):
            values.append(float(value))
    return values


def _metric_mean(rows: Sequence[Mapping[str, Any]], key: str, *, soft_only: bool) -> float:
    return _mean(_metric_values(rows, key, soft_only=soft_only))


def _metric_median(rows: Sequence[Mapping[str, Any]], key: str, *, soft_only: bool) -> float:
    return _median(_metric_values(rows, key, soft_only=soft_only))


def _change_rate(rows: Sequence[Mapping[str, Any]], weight: float) -> float:
    matched = [row for row in rows if row.get("soft_weight") == weight]
    return _rate(sum(1 for row in matched if row.get("top1_changed")), len(matched))


def _top3_mean(rows: Sequence[Mapping[str, Any]], weight: float) -> float:
    values = [float(row["top3_jaccard"]) for row in rows if row.get("soft_weight") == weight]
    return _mean(values)
