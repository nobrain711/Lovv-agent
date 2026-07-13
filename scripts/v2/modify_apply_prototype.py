#!/usr/bin/env python3
"""수정(modification) 적용 프로토타입 — edit_mode 스텁 대신, 픽스처의 modify intent를 전 과정 시뮬.

목적: V2_11 계약 + 우리 설계결정(placeId 타깃·slot 재유도·seed 보호·D1 로컬 재배치·테마균형)을
실제 성공 케이스(파주) 위에서 검증. 재인출 후보는 v2 메타 덤프의 *실제 파주* 장소(임베딩 랭킹만 휴리스틱 대체).
"""
from __future__ import annotations
import json, math, re
from collections import Counter

DUMP = "metadata_audit/kr-tour-domain-v2-all-metadata-20260630T001340Z.json"
FIX = "docs/tasks/results/v2_modify_fixtures/paju_modify_input_01.json"
OUT = "docs/tasks/results/v2_modify_fixtures/paju_modify_applied_01.json"


def hav(a, b):
    R = 6371.0
    la1, lo1 = map(math.radians, a)
    la2, lo2 = map(math.radians, b)
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def drive_min(km):
    return round(km / 40 * 60, 1)  # 프로토타입: driving 40km/h proxy


def nid_of(pid):
    xs = re.findall(r"(\d+)", pid or "")
    return xs[-1] if xs else ""


def slot_label(day_number, day_count, order, count):
    if day_count > 1 and day_number == 1:
        return "evening" if (order == count and count > 1) else "afternoon"
    if day_count > 1 and day_number == day_count:
        return "morning" if order == 1 else "afternoon"
    if order == 1:
        return "morning"
    if order == count:
        return "evening"
    return "afternoon"


def load_paju():
    dump = json.load(open(DUMP, encoding="utf-8"))
    paju = {}
    for r in dump["records"]:
        m = r["metadata"]
        if m.get("entity_type") != "attraction" or (m.get("city_name_ko") or "") != "파주시":
            continue
        nid = nid_of(m.get("ddb_sk", ""))
        try:
            lat = float(m["latitude"]); lon = float(m["longitude"])
        except Exception:
            continue
        paju[nid] = dict(nid=nid, title=m.get("title", ""), tt=list(m.get("theme_tags") or []),
                         st=m.get("attraction_subtype_code", ""), lat=lat, lon=lon,
                         ddb_pk=m.get("ddb_pk", ""), ddb_sk=m.get("ddb_sk", ""))
    return paju


def main():
    paju = load_paju()
    fix = json.load(open(FIX, encoding="utf-8"))
    seeds = {s["placeId"] for s in fix["resume_context"]["seeds"]}
    days = fix["current_itinerary_from_front"]["days"]
    cur_ids = {nid_of(it["placeId"]) for d in days for it in d["items"]}
    notices, changed, failed = [], [], []

    WALK_ST = {"NA040700", "VE030100", "NA020200", "VE040300"}  # 수목원·정원/시민공원/호수/둘레길 = 산책로류
    WALK_KW = re.compile(r"산책로|둘레길|수목원|공원|호수|정원|생태")

    for op in fix["modify_result"]["edit_ops"]:
        tgt = op["target"]; tpid = tgt["placeId"]; tnid = nid_of(tpid)
        # 1) seed 보호
        if tpid in seeds:
            failed.append({"target": tgt, "reason": "seed_protected"})
            notices.append("요청하신 슬롯은 도시 선택 근거(대표 장소)라 변경할 수 없어요.")
            continue
        # 2) 대상 항목 찾기 (placeId로 항목단위)
        loc = None
        for di, d in enumerate(days):
            for ii, it in enumerate(d["items"]):
                if nid_of(it["placeId"]) == tnid:
                    loc = (di, ii)
        if loc is None:
            failed.append({"target": tgt, "reason": "target_not_found"})
            continue
        di, ii = loc; day = days[di]
        # 3) 재인출 풀: 파주 자연·트레킹, 현재 일정 제외, condition 필터 + 근접 랭킹
        cond = op["condition"]; hint = set(cond.get("themes_hint", []))
        others = [(paju[nid_of(it["placeId"])]["lat"], paju[nid_of(it["placeId"])]["lon"])
                  for it in day["items"] if nid_of(it["placeId"]) != tnid and nid_of(it["placeId"]) in paju]
        cx = sum(c[0] for c in others) / len(others); cy = sum(c[1] for c in others) / len(others)
        pool = []
        for nid, p in paju.items():
            if nid in cur_ids:
                continue
            if hint and not (set(p["tt"]) & hint):
                continue
            cmatch = (2 if p["st"] in WALK_ST else 0) + (1 if WALK_KW.search(p["title"]) else 0)
            prox = hav((cx, cy), (p["lat"], p["lon"]))
            pool.append((cmatch, -prox, p))
        if not pool:
            failed.append({"target": tgt, "reason": "no_candidate"})
            notices.append("조건에 맞는 대체 장소를 찾지 못해 기존 장소를 유지했어요.")
            continue
        pool.sort(key=lambda x: (x[0], x[1]), reverse=True)
        pick = pool[0][2]
        old = day["items"][ii]
        day["items"][ii] = {"order": old["order"], "slot": old["slot"],
                            "placeId": f"attraction#{pick['nid']}", "title": pick["title"],
                            "theme_tags": pick["tt"], "is_seed": False,
                            "ddb_pk": pick["ddb_pk"], "ddb_sk": pick["ddb_sk"],
                            "copy_source": "modify_reretrieve",
                            "_reretrieve": {"cmatch": pool[0][0], "condition": cond,
                                            "pool_size": len(pool)}}
        changed.append({"day": day["day"], "from": old["placeId"], "from_title": old["title"],
                        "to": f"attraction#{pick['nid']}", "to_title": pick["title"]})
        cur_ids.add(pick["nid"])

    # 5) 로컬 재배치: 영향받은 날만 seed anchor에서 NN, 나머지 freeze
    day_count = len(days)
    affected = {c["day"] for c in changed}
    for d in days:
        if d["day"] not in affected:
            continue
        items = d["items"]
        coords = {nid_of(it["placeId"]): (paju[nid_of(it["placeId"])]["lat"], paju[nid_of(it["placeId"])]["lon"])
                  for it in items if nid_of(it["placeId"]) in paju}
        seed_it = [it for it in items if it["is_seed"]]
        start = seed_it[0] if seed_it else items[0]
        ordered = [start]; rest = [it for it in items if it is not start]
        while rest:
            last = coords[nid_of(ordered[-1]["placeId"])]
            rest.sort(key=lambda it: hav(last, coords[nid_of(it["placeId"])]))
            ordered.append(rest.pop(0))
        for i, it in enumerate(ordered, 1):
            it["order"] = i
            it["slot"] = slot_label(d["day"], day_count, i, len(ordered))
            it["moveMinutes"] = 0 if i == 1 else drive_min(
                hav(coords[nid_of(ordered[i - 2]["placeId"])], coords[nid_of(it["placeId"])]))
        d["items"] = ordered

    # 6) 테마 균형
    tc = Counter()
    for d in days:
        for it in d["items"]:
            for t in it["theme_tags"]:
                tc[t] += 1
    req = fix["resume_context"]["active_required_themes"]
    seed_theme = {s["theme"] for s in fix["resume_context"]["seeds"]}
    for t in req:
        if tc[t] == 0:
            notices.append(f"수정으로 [{t}] 장소가 없어졌어요. 균형을 위해 조정이 필요할 수 있어요.")
        elif tc[t] == 1 and t in seed_theme:
            pass  # seed floor로 최소 1 유지 → 조용히 진행

    out = {"thread_id": fix["thread_id"], "response_status": "modification_pending",
           "itinerary": {"tripType": fix["resume_context"]["trip_type"], "days": days},
           "modification": {"changed_slots": changed, "failed_slots": failed,
                            "user_notice": " ".join(notices) or None, "theme_balance": dict(tc)}}
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print("=== 적용 결과 (파주 2d1n) ===")
    for d in days:
        for it in d["items"]:
            s = "★" if it["is_seed"] else " "
            print(f"  D{d['day']} {it['slot']:<9}{s} {it['title'][:20]:<20} "
                  f"{('|'.join(it['theme_tags']))[:10]:<10} move={it.get('moveMinutes')}")
    print("\nchanged:", json.dumps(changed, ensure_ascii=False))
    print("failed:", failed)
    print("theme_balance:", dict(tc), "(요청", req, ")")
    print("notice:", " ".join(notices) or "(없음)")


if __name__ == "__main__":
    main()
