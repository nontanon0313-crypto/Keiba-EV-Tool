"""NAR過去データ一括取得。並列・中断再開可能。進捗を詳細に表示。

使い方:
  python3 -m backend.scripts.bulk_fetch_nar 2024-01-01 2024-12-31
  python3 -m backend.scripts.bulk_fetch_nar 2024-01-01 2024-12-31 5000
  FORCE_REDO=1 python3 -m backend.scripts.bulk_fetch_nar 2023-01-01 2024-12-31 5256
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
LOG_PATH = "nar_refetch.log"
SPONSOR_TO_VENUE = {
    "06": "水沢", "13": "浦和", "20": "笠松", "26": "園田",
    "29": "高知", "55": "大井", "61": "川崎", "03": "船橋",
    "11": "門別", "41": "名古屋", "43": "金沢", "04": "船橋", "18": "名古屋", "30": "川崎", "33": "金沢",
}


class Progress:
    def __init__(self, target, log_path=None, interval=3.0):
        self.t0 = time.time()
        self.target = target
        self.last = 0.0
        self.interval = interval
        self.fh = None
        if log_path:
            try:
                self.fh = open(log_path, "a", buffering=1)
            except Exception:
                self.fh = None

    def _write(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        print(line, flush=True)
        if self.fh:
            try:
                self.fh.write(line + "\n")
            except Exception:
                pass

    def log(self, msg):
        self._write(msg)

    def tick(self, stats, force=False):
        now = time.time()
        if not force and (now - self.last) < self.interval:
            return
        self.last = now
        processed = stats["total"] + stats["skipped"] + stats["failed"] + stats.get("empty", 0)
        elapsed = now - self.t0
        rate = processed / elapsed if elapsed > 0 else 0.0
        remain = max(0, self.target - stats["total"])
        eta = remain / rate if rate > 0 else 0.0
        self._write(
            f"[progress] new={stats['total']} skip={stats['skipped']} empty={stats.get('empty', 0)} "
            f"fail={stats['failed']} processed={processed} elapsed={elapsed:.0f}s "
            f"rate={rate:.2f}/s target={self.target} remain={remain} eta={eta:.0f}s"
        )


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


async def _bump(stats, lock, key, prog):
    async with lock:
        stats[key] = stats.get(key, 0) + 1
        prog.tick(stats)


async def process_race(client, sem, inner_sem, date, track_cd, sponsor_cd, race_nb, detail,
                       existing_races, existing_odds, stats, lock, target, prog):
    async with sem:
        if stats["total"] >= target:
            return
        rid = f"nar-{date}-{track_cd}-{race_nb}"
        force = os.getenv("FORCE_REDO", "") == "1"
        if not force and rid in existing_races and rid in existing_odds:
            await _bump(stats, lock, "skipped", prog)
            return
        try:
            shutuba = await asyncio.to_thread(fetch_shutuba, date, track_cd, sponsor_cd, race_nb)
            if not shutuba or not shutuba.get("runners"):
                await _bump(stats, lock, "empty", prog)
                return
            payload = _build_payload(date, track_cd, sponsor_cd, race_nb, shutuba, detail)
            result = await asyncio.to_thread(fetch_result, date, track_cd, sponsor_cd, race_nb)
            if result:
                payload["result_runners"] = result.get("runners", [])
                payload["finish_order"] = result.get("finish_order", [])
                payload["payouts"] = result.get("payouts", {})
                if result.get("surface"):
                    payload["surface"] = result["surface"]
                if result.get("distance"):
                    payload["distance"] = result["distance"]
            race_store.save_race(rid, payload)
            existing_races.add(rid)
            num_runners = len(payload["runners"])
            odds = await fetch_odds_all_full_async(
                client, date, track_cd, sponsor_cd, race_nb, num_runners,
                inner_sem=inner_sem,
            )
            if odds:
                odds_store.save_odds(rid, odds)
                existing_odds.add(rid)
            await _bump(stats, lock, "total", prog)
        except Exception as e:
            async with lock:
                stats["failed"] += 1
                prog.tick(stats)
            prog.log(f"  fail {rid}: {str(e)[:120]}")


async def main_async(date_from, date_to, target):
    prog = Progress(target=target, log_path=LOG_PATH, interval=3.0)
    existing_races = set(race_store.list_race_ids())
    existing_odds = set(odds_store.list_race_ids())
    force = os.getenv("FORCE_REDO", "") == "1"
    prog.log(f"[nar] start {date_from}〜{date_to} target={target} "
             f"existing_races={len(existing_races)} existing_odds={len(existing_odds)}")
    prog.log(f"[nar] concurrency={CONCURRENCY} inner={INNER_CONCURRENCY} force_redo={force}")

    stats = {"total": 0, "skipped": 0, "failed": 0, "empty": 0, "t0": time.time()}
    sem = asyncio.Semaphore(CONCURRENCY)
    inner_sem = asyncio.Semaphore(INNER_CONCURRENCY)
    lock = asyncio.Lock()

    d0 = datetime.strptime(date_from, "%Y-%m-%d")
    d1 = datetime.strptime(date_to, "%Y-%m-%d")
    total_days = (d1 - d0).days + 1

    async with httpx.AsyncClient(headers=HEADERS) as client:
        d = d0
        day_idx = 0
        while d <= d1:
            if stats["total"] >= target:
                prog.log(f"[nar] target reached ({stats['total']}), stopping")
                break
            day_idx += 1
            date_str = d.strftime("%Y%m%d")
            day_label = d.strftime("%Y-%m-%d")
            prog.log(f"=== day {day_idx}/{total_days} {day_label} ===")
            venues = await fetch_race_list_async(client, date_str)
            if not venues:
                prog.log("  no venues")
                prog.tick(stats, force=True)
                d += timedelta(days=1)
                continue
            venue_labels = [SPONSOR_TO_VENUE.get(sp, tc) for (tc, sp) in venues]
            prog.log(f"  venues={len(venues)}: {venue_labels}")
            for vi, (track_cd, sponsor_cd) in enumerate(venues, 1):
                if stats["total"] >= target:
                    break
                venue_name = SPONSOR_TO_VENUE.get(sponsor_cd, track_cd)
                race_nbs = await fetch_one_day_races_async(client, date_str, track_cd, sponsor_cd)
                if not race_nbs:
                    prog.log(f"  [{vi}/{len(venues)}] {venue_name} no races")
                    continue
                try:
                    details_list = await asyncio.to_thread(fetch_one_day_detail, track_cd, sponsor_cd, date_str)
                    details = {x["race_nb"]: x for x in details_list}
                except Exception as e:
                    prog.log(f"  [{vi}/{len(venues)}] {venue_name} detail fetch failed: {str(e)[:80]}")
                    details = {}
                before_new = stats["total"]
                prog.log(f"  [{vi}/{len(venues)}] {venue_name} {len(race_nbs)}R start")
                tasks = []
                for rn in race_nbs:
                    tasks.append(process_race(
                        client, sem, inner_sem, date_str, track_cd, sponsor_cd, rn,
                        details.get(rn, {}), existing_races, existing_odds,
                        stats, lock, target, prog,
                    ))
                await asyncio.gather(*tasks, return_exceptions=True)
                prog.log(f"  [{vi}/{len(venues)}] {venue_name} done new={stats['total']-before_new} R (total_new={stats['total']})")
                prog.tick(stats, force=True)
            d += timedelta(days=1)

    elapsed = time.time() - stats["t0"]
    prog.log(f"[nar] done new={stats['total']} skipped={stats['skipped']} empty={stats['empty']} "
             f"failed={stats['failed']} elapsed={elapsed:.0f}s")
    if prog.fh:
        try:
            prog.fh.flush()
        except Exception:
            pass
    os._exit(0)


def main():
    date_from = sys.argv[1] if len(sys.argv) > 1 else "2024-01-01"
    date_to = sys.argv[2] if len(sys.argv) > 2 else "2024-12-31"
    target = int(sys.argv[3]) if len(sys.argv) > 3 else 5000
    asyncio.run(main_async(date_from, date_to, target))


if __name__ == "__main__":
    main()
