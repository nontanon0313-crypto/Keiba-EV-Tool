"""NAR過去データ一括取得。並列・中断再開可能。
使い方:
  python3 -m backend.scripts.bulk_fetch_nar 2024-01-01 2024-12-31
  python3 -m backend.scripts.bulk_fetch_nar 2024-01-01 2024-12-31 5000
"""
import os
import sys
import asyncio
import time
from datetime import datetime, timedelta

import httpx

from backend.app.services import race_store, odds_store
from backend.scraper.oddspark_keiba import (
    fetch_shutuba, fetch_odds_all_full, fetch_result, fetch_one_day_detail,
    fetch_odds_all_full_async,
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Mobile Safari/537.36",
    "Referer": "https://www.oddspark.com/keiba/",
}
CONCURRENCY = 16
INNER_CONCURRENCY = 8
SPONSOR_TO_VENUE = {
    "06": "水沢", "13": "浦和", "20": "笠松", "26": "園田",
    "29": "高知", "55": "大井", "61": "川崎", "03": "船橋",
    "11": "門別", "41": "名古屋", "43": "金沢", "04": "船橋", "18": "名古屋", "30": "川崎", "33": "金沢",
}


def _parse_race_name(name):
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


async def fetch_race_list_async(client, date):
    url = f"https://www.oddspark.com/keiba/KaisaiRaceList.do?raceDy={date}"
    try:
        r = await client.get(url, timeout=20, follow_redirects=True)
        if r.status_code != 200:
            return []
        import re
        pattern = rf"OneDayRaceList\.do\?raceDy={date}&amp;opTrackCd=(\d+)&amp;sponsorCd=(\d+)"
        pairs = set()
        for m in re.finditer(pattern, r.text):
            pairs.add((m.group(1), m.group(2)))
        return sorted(pairs)
    except Exception:
        return []


async def fetch_one_day_races_async(client, date, track_cd, sponsor_cd):
    url = f"https://www.oddspark.com/keiba/OneDayRaceList.do?raceDy={date}&opTrackCd={track_cd}&sponsorCd={sponsor_cd}"
    try:
        r = await client.get(url, timeout=20, follow_redirects=True)
        if r.status_code != 200:
            return []
        import re
        return sorted(set(int(m.group(1)) for m in re.finditer(r"raceNb=(\d+)", r.text)))
    except Exception:
        return []


def _build_payload(date, track_cd, sponsor_cd, race_nb, shutuba, detail):
    venue, rn = _parse_race_name(shutuba.get("race_name", ""))
    start_hhmm = (detail or {}).get("start_hhmm") or "12:00"
    hh, mm = start_hhmm.split(":")[:2]
    start_iso = f"{date[:4]}-{date[4:6]}-{date[6:8]}T{int(hh):02d}:{int(mm):02d}:00"
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
            "horse_id": "", "horse_name": r.get("horse_name", ""),
            "jockey": r.get("jockey", ""), "trainer": "",
            "weight": 55.0,
            "horse_weight": r.get("horse_weight"),
            "horse_weight_change": None,
            "odds_win": r.get("odds_win") or 50.0,
            "popularity": r.get("popularity"),
            "status": "出走",
        })
    return {
        "race_id": f"nar-{date}-{track_cd}-{race_nb}",
        "venue": venue, "date": f"{date[:4]}-{date[4:6]}-{date[6:8]}",
        "race_number": rn,
        "start_at": start_iso, "deadline_at": deadline_iso,
        "surface": surface, "distance": distance,
        "runners": runners,
        "source": "oddspark", "track_cd": track_cd, "sponsor_cd": sponsor_cd,
        "race_nb": race_nb,
    }


async def process_race(client, sem, inner_sem, date, track_cd, sponsor_cd, race_nb, detail, existing_races, existing_odds, stats, lock, target):
    async with sem:
        if stats["total"] >= target:
            return
        rid = f"nar-{date}-{track_cd}-{race_nb}"
        # 既存スキップ
        if rid in existing_races and rid in existing_odds:
            async with lock:
                stats["skipped"] += 1
            return
        try:
            shutuba = await asyncio.to_thread(fetch_shutuba, date, track_cd, sponsor_cd, race_nb)
            if not shutuba or not shutuba.get("runners"):
                return
            payload = _build_payload(date, track_cd, sponsor_cd, race_nb, shutuba, detail)
            # 結果
            result = await asyncio.to_thread(fetch_result, date, track_cd, sponsor_cd, race_nb)
            if result:
                # 結果でpayloadを上書き（結果のrunners/着順/払戻を使用）
                payload["result_runners"] = result.get("runners", [])
                payload["finish_order"] = result.get("finish_order", [])
                payload["payouts"] = result.get("payouts", {})
                if result.get("surface"):
                    payload["surface"] = result["surface"]
                if result.get("distance"):
                    payload["distance"] = result["distance"]
            race_store.save_race(rid, payload)
            existing_races.add(rid)
            # オッズ
            num_runners = len(payload["runners"])
            odds = await fetch_odds_all_full_async(
                client, date, track_cd, sponsor_cd, race_nb, num_runners,
                inner_sem=inner_sem,
            )
            if odds:
                odds_store.save_odds(rid, odds)
                existing_odds.add(rid)
            async with lock:
                stats["total"] += 1
                if stats["total"] % 20 == 0:
                    elapsed = time.time() - stats["t0"]
                    rate = stats["total"] / elapsed if elapsed else 0
                    print(f"  [progress] total={stats['total']} skipped={stats['skipped']} elapsed={elapsed:.0f}s rate={rate:.2f}/s", flush=True)
        except Exception as e:
            async with lock:
                stats["failed"] += 1
            print(f"  fail {rid}: {str(e)[:80]}", flush=True)


async def main_async(date_from, date_to, target):
    existing_races = set(race_store.list_race_ids())
    existing_odds = set(odds_store.list_race_ids())
    print(f"[nar] start {date_from}〜{date_to} target={target} existing_races={len(existing_races)} existing_odds={len(existing_odds)}", flush=True)

    stats = {"total": 0, "skipped": 0, "failed": 0, "t0": time.time()}
    sem = asyncio.Semaphore(CONCURRENCY)
    inner_sem = asyncio.Semaphore(INNER_CONCURRENCY)
    lock = asyncio.Lock()

    d0 = datetime.strptime(date_from, "%Y-%m-%d")
    d1 = datetime.strptime(date_to, "%Y-%m-%d")
    async with httpx.AsyncClient(headers=HEADERS) as client:
        d = d0
        while d <= d1:
            if stats["total"] >= target:
                break
            date_str = d.strftime("%Y%m%d")
            venues = await fetch_race_list_async(client, date_str)
            if not venues:
                d += timedelta(days=1)
                continue
            print(f"[{date_str}] venues={len(venues)}", flush=True)
            for (track_cd, sponsor_cd) in venues:
                if stats["total"] >= target:
                    break
                race_nbs = await fetch_one_day_races_async(client, date_str, track_cd, sponsor_cd)
                if not race_nbs:
                    continue
                # 発走時刻・距離
                try:
                    details_list = await asyncio.to_thread(fetch_one_day_detail, track_cd, sponsor_cd, date_str)
                    details = {x["race_nb"]: x for x in details_list}
                except Exception:
                    details = {}
                print(f"  {SPONSOR_TO_VENUE.get(sponsor_cd, track_cd)} {len(race_nbs)}R", flush=True)
                tasks = []
                for rn in race_nbs:
                    tasks.append(process_race(client, sem, inner_sem, date_str, track_cd, sponsor_cd, rn, details.get(rn, {}), existing_races, existing_odds, stats, lock, target))
                await asyncio.gather(*tasks, return_exceptions=True)
            d += timedelta(days=1)
    elapsed = time.time() - stats["t0"]
    print(f"[nar] done total={stats['total']} skipped={stats['skipped']} failed={stats['failed']} elapsed={elapsed:.0f}s", flush=True)
    os._exit(0)


def main():
    date_from = sys.argv[1] if len(sys.argv) > 1 else "2024-01-01"
    date_to = sys.argv[2] if len(sys.argv) > 2 else "2024-12-31"
    target = int(sys.argv[3]) if len(sys.argv) > 3 else 5000
    asyncio.run(main_async(date_from, date_to, target))


if __name__ == "__main__":
    main()
