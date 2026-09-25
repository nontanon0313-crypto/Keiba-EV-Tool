"""毎日の地方競馬データ取得。Tursoに保存。"""
import os
import sys
import time
from datetime import datetime

from backend.scraper.oddspark_keiba import (
    fetch_race_list, fetch_one_day, fetch_one_day_detail, fetch_shutuba,
    fetch_odds_all_full, fetch_result,
)
from backend.app.services import odds_store
from backend.app.services import race_store


def parse_race_name(name: str):
    """race_name から 競馬場, レース番号, 発走時刻を抽出。"""
    import re
    venue = ""
    m = re.search(r"(\S+競馬)", name)
    if m:
        venue = m.group(1).replace("競馬", "")
    rn = 0
    m2 = re.search(r"(\d+)R", name)
    if m2:
        rn = int(m2.group(1))
    return venue, rn


def build_payload(date: str, track_cd: str, sponsor_cd: str, race_nb: int, shutuba: dict, detail: dict = None) -> dict:
    """race_store 用の payload を組み立てる。"""
    venue, rn = parse_race_name(shutuba.get("race_name", ""))
    # 発走時刻
    start_hhmm = (detail or {}).get("start_hhmm") or "12:00"
    hh, mm = start_hhmm.split(":")[:2]
    start_iso = f"{date[:4]}-{date[4:6]}-{date[6:8]}T{int(hh):02d}:{int(mm):02d}:00"
    # 締切 = 発走 2分前
    import datetime as dt
    try:
        st = dt.datetime.fromisoformat(start_iso)
        deadline_iso = (st - dt.timedelta(minutes=2)).isoformat()
    except Exception:
        deadline_iso = start_iso
    distance = (detail or {}).get("distance", 0) or 0
    surface = (detail or {}).get("surface", "ダート") or "ダート"
    runners = []
    for r in shutuba.get("runners", []):
        runners.append({
            "horse_number": r.get("horse_number", 0),
            "frame_number": r.get("frame_number", 0),
            "horse_id": "",
            "horse_name": r.get("horse_name", ""),
            "jockey": r.get("jockey", ""),
            "trainer": "",
            "weight": 55.0,
            "horse_weight": r.get("horse_weight"),
            "horse_weight_change": None,
            "odds_win": r.get("odds_win") or 50.0,
            "popularity": r.get("popularity"),
            "status": "出走",
        })
    race_id = f"nar-{date}-{track_cd}-{race_nb}"
    return {
        "race_id": race_id,
        "venue": venue,
        "date": f"{date[:4]}-{date[4:6]}-{date[6:8]}",
        "race_number": rn,
        "start_at": start_iso,
        "deadline_at": deadline_iso,
        "surface": surface,
        "distance": distance,
        "runners": runners,
        "source": "oddspark",
        "track_cd": track_cd,
        "sponsor_cd": sponsor_cd,
        "race_nb": race_nb,
    }


def main():
    date = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y%m%d")
    print(f"[daily_fetch] date={date}", flush=True)

    venues = fetch_race_list(date)
    print(f"[daily_fetch] venues={len(venues)}", flush=True)

    total = 0
    for v in venues:
        track_cd = v["track_cd"]
        sponsor_cd = v["sponsor_cd"]
        venue = v["venue"]
        races = fetch_one_day(track_cd, sponsor_cd, date)
        if not races:
            print(f"  {venue}: no races", flush=True)
            continue
        # 発走時刻・距離を取得
        try:
            details = {d["race_nb"]: d for d in fetch_one_day_detail(track_cd, sponsor_cd, date)}
        except Exception:
            details = {}
        print(f"  {venue} ({track_cd}/{sponsor_cd}): {len(races)} races", flush=True)
        for r in races:
            try:
                shutuba = fetch_shutuba(date, track_cd, sponsor_cd, r["race_nb"])
                if not shutuba or not shutuba.get("runners"):
                    continue
                detail = details.get(r["race_nb"], {})
                payload = build_payload(date, track_cd, sponsor_cd, r["race_nb"], shutuba, detail)
                race_store.save_race(payload["race_id"], payload)

                # 全券種オッズ取得・保存
                num_runners = len(payload["runners"])
                odds = fetch_odds_all_full(date, track_cd, sponsor_cd, r["race_nb"], num_runners)
                if odds:
                    odds_store.save_odds(payload["race_id"], odds)

                # 結果取得 (発走後なら取得可能)
                try:
                    res = fetch_result(date, track_cd, sponsor_cd, r["race_nb"])
                    if res and res.get("finish_order"):
                        payload["finish_order"] = res["finish_order"]
                        payload["payouts"] = res.get("payouts", {})
                        if res.get("runners"):
                            payload["result_runners"] = res["runners"]
                        if res.get("surface"):
                            payload["surface"] = res["surface"]
                        if res.get("distance"):
                            payload["distance"] = res["distance"]
                        race_store.save_race(payload["race_id"], payload)
                except Exception as e:
                    print(f"    [result] {payload['race_id']} skip: {str(e)[:60]}", flush=True)

                total += 1
                print(f"    saved {payload['race_id']} ({len(payload['runners'])}頭)", flush=True)
            except Exception as e:
                print(f"    fail {r}: {str(e)[:80]}", flush=True)
            time.sleep(2.0)
    print(f"[daily_fetch] done total={total}", flush=True)
    os._exit(0)


if __name__ == "__main__":
    main()
