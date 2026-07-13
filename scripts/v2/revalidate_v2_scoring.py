#!/usr/bin/env python3
"""업데이트된 v2 city_select scoring(리팩터된 scoring/ 서브패키지)으로 retrieval 데이터 전수 재검증.

- **실제 코드 그대로 실행**: `scoring.service.score_city` import(마운트 손상 없음 확인).
- congestion(resolve_w_cong·congestion_index)은 ranking.py의 순수 로직을 그대로 복제(그 파일은 domain 의존 있어 함수만 이식).
- 데이터: 최신 v2 retrieval smoke(094517, 53케이스) + 방문객 stats(121521 city_stats.json) + intent mock(trip_type·user_location·congestion_pref·destination).
- 산출: case_id→선택도시(신규 full formula) + 기존 selected_cities.json(구 offline_rescore)과 diff.

사용: python scripts/v2/revalidate_v2_scoring.py
"""
from __future__ import annotations
import sys, os, json, glob, math
sys.path.insert(0, "src")
from lovv_agent_v2.agents.city_select.scoring.service import score_city, score_place, CANDIDATE_SUFFICIENCY_THRESHOLD
from lovv_agent_v2.agents.city_select.scoring.selection import TRIP_CANDIDATE_BUDGETS

SMOKE = "docs/tasks/results/v2_retrieval_smoke/20260630T094517"
STATS = "docs/tasks/results/v2_retrieval_smoke/20260629T121521/city_stats.json"
MOCKS = "docs/tasks/results/v2_intent_mocks"
STAT_YEAR = "2025"  # stats 파일 연도

W_CONG = {"quiet": 0.08, "vibrant": -0.05, "neutral": 0.03}
_SRC = {"v2", "gen", "v2mock", "v1dump", "mod", "short", "v1", "dump", "wrapped", "pair", "triple"}


def stem(name):
    base = os.path.splitext(os.path.basename(name))[0].lower()
    toks = base.split("_"); i = 0
    while i < len(toks) and (toks[i].isdigit() or toks[i] in _SRC):
        i += 1
    return "_".join(toks[i:])


def resolve_w_cong(pref):
    return W_CONG.get(pref, W_CONG["neutral"])


def congestion_index_by_city(visitor_by_city):
    known = {c: v for c, v in visitor_by_city.items() if v is not None and v > 0}
    if len(known) < 2:
        return {c: 0.5 for c in visitor_by_city}
    logs = {c: math.log(v) for c, v in known.items()}
    lo, hi = min(logs.values()), max(logs.values())
    if lo == hi:
        return {c: 0.5 for c in visitor_by_city}
    res = {c: 0.5 for c in visitor_by_city}
    for c, lv in logs.items():
        res[c] = (lv - lo) / (hi - lo)
    return res


def load_mocks():
    m = {}
    for path in glob.glob(os.path.join(MOCKS, "generation", "*.json")) + glob.glob(os.path.join(MOCKS, "*.json")):
        try:
            obj = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        io = obj.get("intent_output", obj)
        if not isinstance(io, dict):
            continue
        m[stem(path)] = io
    return m


def infer(case_id, io):
    """mock 없으면 case_id/기본으로 보강."""
    trip = None
    for t in ("daytrip", "2d1n", "3d2n", "4d3n", "5d4n"):
        if t in case_id:
            trip = t
    if io:
        return (io.get("trip_type") or trip, io.get("user_location"),
                io.get("congestion_pref") or "neutral",
                io.get("destination_id") or io.get("fixed_city_id"),
                io.get("travel_month"))
    return (trip, None, "neutral", ("gyeongju" if "anchored" in case_id else None), None)


def city_pk_norm(pk):
    return (pk or "").upper()


def anchor_pk_for_destination(dest, pk_by_city_id):
    if not dest:
        return None
    text = str(dest).strip()
    if not text:
        return None
    if text.startswith("CITY#"):
        return city_pk_norm(text)
    return pk_by_city_id.get(text) or f"CITY#{text.upper()}"


def trip_candidate_budget(trip):
    return TRIP_CANDIDATE_BUDGETS.get(trip, CANDIDATE_SUFFICIENCY_THRESHOLD)


def main():
    stats = json.load(open(STATS, encoding="utf-8"))
    mocks = load_mocks()
    old_sel = json.load(open(os.path.join(SMOKE, "selected_cities.json"), encoding="utf-8"))
    files = [f for f in sorted(glob.glob(os.path.join(SMOKE, "*.json")))
             if not os.path.basename(f).startswith(("selected_", "rescore_", "_summary", "city_stats"))]
    new_sel = {}
    rows = []
    for f in files:
        d = json.load(open(f, encoding="utf-8"))
        cid = d.get("case_id") or os.path.basename(f)
        themes = d.get("query", {}).get("themes", []) or []
        io = mocks.get(stem(cid), {})
        trip, uloc, cpref, dest, tmonth = infer(cid, io)
        # 후보 그룹핑 by city(ddb_pk)
        pt = d.get("channels", {}).get("raw", {}).get("per_theme", {}) or {}
        by_city = {}
        pk_by_city_id = {}
        seen = set()
        for th in themes:
            for r in (pt.get(th, {}) or {}).get("ranked", []):
                pid = r.get("place_id")
                if pid in seen:
                    continue
                seen.add(pid)
                pk = city_pk_norm(r.get("ddb_pk"))
                if not pk:
                    continue
                rec = dict(r); rec["entity_type"] = "attraction"
                city_id = rec.get("city_id")
                if isinstance(city_id, str) and city_id:
                    pk_by_city_id.setdefault(city_id, pk)
                by_city.setdefault(pk, []).append(rec)
        if not by_city:
            new_sel[cid] = None; continue
        # anchored: 도시 고정
        if dest:
            anchor_pk = anchor_pk_for_destination(dest, pk_by_city_id)
            # 후보풀에 있으면 그걸로, 없으면 그대로 표기
            new_sel[cid] = anchor_pk
            rows.append((cid, "[A]", old_sel.get(cid), new_sel[cid], "anchored"))
            continue
        # congestion
        mm = f"{int(tmonth):02d}" if tmonth else None
        visitor = {}
        for pk in by_city:
            s = stats.get(pk) or {}
            bm = s.get("by_month") or {}
            v = bm.get(f"{STAT_YEAR}{mm}") if mm else s.get("annual_visitors")
            visitor[pk] = v if isinstance(v, (int, float)) else None
        cong = congestion_index_by_city(visitor)
        w_cong = resolve_w_cong(cpref)
        budget = trip_candidate_budget(trip)
        # score each city
        ranked = []
        for pk, places in by_city.items():
            scored = [sp for sp in (score_place(p, themes) for p in places) if sp.scored]
            if not scored:
                continue
            res = score_city(city_id=pk, places=scored, active_themes=themes,
                             user_location=uloc, primary_budget=budget,
                             congestion_index=cong.get(pk, 0.5), w_cong=w_cong,
                             theme_weights=None, trip_type=trip)
            ranked.append((res.city_score, res.candidate_count, pk, res.breakdown))
        ranked.sort(key=lambda x: (x[0], x[1]), reverse=True)
        top = ranked[0]
        new_sel[cid] = top[2]
        oldc = old_sel.get(cid)
        flag = "  " if oldc == top[2] else "≠≠"
        rows.append((cid, flag, oldc, top[2], f"score={top[0]} cong_w={w_cong} n={top[1]}"))

    json.dump(new_sel, open(os.path.join(SMOKE, "selected_cities_v2score.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    # 비교
    changed = [(c, o, n) for c, o, n in ((r[0], r[2], r[3]) for r in rows) if o and n and o != n]
    print(f"재검증 {len(rows)}케이스 · 변경 {len(changed)}건 (구 offline_rescore → 신 full formula)")
    print("=" * 70)
    for cid, flag, oldc, newc, note in rows:
        print(f" {flag} {cid[:44]:<44} {str(oldc):<22}->{str(newc):<22} {note}")
    print("\n--- 변경된 케이스 ---")
    for c, o, n in changed:
        print(f"  {c}: {o} -> {n}")
    print(f"\n저장: {os.path.join(SMOKE,'selected_cities_v2score.json')}")


if __name__ == "__main__":
    main()
