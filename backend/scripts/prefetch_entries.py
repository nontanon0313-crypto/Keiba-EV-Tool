"""未来レースの出走表 (ent1) を事前取得して prefetched_entries に保存する。

使い方:
    python3 -m backend.scripts.prefetch_entries              # 今日から7日先まで
    python3 -m backend.scripts.prefetch_entries 14           # 14日先まで
    python3 -m backend.scripts.prefetch_entries 7 force      # 既存も上書き
"""
import os
import sys
import asyncio
import time
import re
from datetime import datetime, timedelta

import httpx
from bs4 import BeautifulSoup

from backend.app.services import entry_store
from backend.scraper.oddspark_keiba import fetch_one_day_detail, fetch_shutuba
from backend.scripts.bulk_fetch_nar import fetch_race_list_async, fetch_one_day_races_async

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Mobile Safari/537.36",
    "Referer": "https://www.oddspark.com/keiba/",
}
CONCURRENCY = 8
LOG_PATH = "prefetch_entries.log"


def _log(msg):
    line = "[" + datetime.now().strftime("%H:%M:%S") + "] " + msg
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


async def _fetch_ent1(client, sem, date, track_cd, sponsor_cd, race_nb):
    url = ("https://www.oddspark.com/keiba/RaceList.do?raceDy=" + str(date)
           + "&opTrackCd=" + str(track_cd)
           + "&sponsorCd=" + str(sponsor_cd)
           + "&raceNb=" + str(race_nb))
    async with sem:
        try:
            r = await client.get(url, timeout=20, follow_redirects=True)
            if r.status_code != 200:
                return None
            html = r.text
        except Exception:
            return None
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.ent1")
    if table is None:
        return None
    title_el = soup.find("title")
    race_name = title_el.get_text(strip=True) if title_el else ""
    runners = []
    prev_frame = 1
    prev_num = 0
    for row in table.find_all("tr"):
        cells = row.find_all(["td", "th"])
        if len(cells) >= 16:
            try:
                frame = int(cells[0].get_text(strip=True))
                num = int(cells[2].get_text(strip=True))
            except (ValueError, IndexError):
                continue
            name_cell = cells[5]
            jw_cell = cells[6]
            odds_cell = cells[7]
            w_cell = cells[8]
        elif len(cells) >= 12:
            try:
                num = int(cells[0].get_text(strip=True))
            except (ValueError, IndexError):
                continue
            frame = prev_frame
            name_cell = cells[3]
            jw_cell = cells[4]
            odds_cell = cells[5]
            w_cell = cells[6]
        else:
            continue
        a = name_cell.find("a", href=re.compile(r"lineageNb="))
        lineage_nb = ""
        if a:
            m = re.search(r"lineageNb=(\d+)", a.get("href", ""))
            if m:
                lineage_nb = m.group(1)
        horse_name = ""
        if a:
            horse_name = a.get_text(strip=True)
        full_txt = name_cell.get_text(" ", strip=True)
        m2 = re.search(r"[牡牝セ]\s*\d+", full_txt)
        age_sex = re.sub(r"\s+", "", m2.group(0)) if m2 else ""
        jw_txt = jw_cell.get_text(" ", strip=True)
        jockey = ""
        weight = None
        mj = re.match(r"([^\d]+)", jw_txt)
        if mj:
            jockey = mj.group(1).strip()
        mw = re.search(r"(\d+\.?\d*)", jw_txt)
        if mw:
            try:
                weight = float(mw.group(1))
            except Exception:
                weight = None
        odds_txt = odds_cell.get_text(" ", strip=True)
        mo = re.search(r"([\d.]+)\s*(\d+)人気", odds_txt)
        odds_win = float(mo.group(1)) if mo else None
        popularity = int(mo.group(2)) if mo else None
        wt = w_cell.get_text(strip=True)
        mh = re.search(r"(\d+)", wt)
        horse_weight = int(mh.group(1)) if mh else None
        runners.append({
            "frame_number": frame,
            "horse_number": num,
            "horse_name": horse_name,
            "jockey": jockey,
            "weight": weight,
            "horse_weight": horse_weight,
            "odds_win": odds_win,
            "popularity": popularity,
            "lineage_nb": lineage_nb,
            "age_sex": age_sex,
            "status": "出走",
        })
        prev_frame = frame
        prev_num = num
    return {
        "race_name": race_name,
        "track_cd": track_cd,
        "sponsor_cd": sponsor_cd,
        "race_nb": race_nb,
        "runners": runners,
    }


async def main_async(days_ahead=7, force=False):
    # Turso クライアントは entry_store が内部で turso_client 経由で取得する。
    # ここで直接 create_client_sync すると aiohttp セッションが二重になり、
    # Render 無料プラン (512MB) でメモリ超過 kill の原因になる。
    today = datetime.now().date()
    dates = [(today + timedelta(days=i)).strftime("%Y%m%d") for i in range(0, days_ahead + 1)]
    tasks = []
    async with httpx.AsyncClient(headers=HEADERS) as client:
        for d in dates:
            try:
                venues = await fetch_race_list_async(client, d)
            except Exception:
                continue
            if not venues:
                continue
            for (tc, sc) in venues:
                try:
                    race_nbs = await fetch_one_day_races_async(client, d, tc, sc)
                except Exception:
                    continue
                details = {}
                try:
                    details_list = await asyncio.to_thread(fetch_one_day_detail, tc, sc, d)
                    details = {x["race_nb"]: x for x in details_list}
                except Exception:
                    details = {}
                for rn in race_nbs or []:
                    tasks.append((d, tc, sc, rn, details.get(rn, {})))
        _log("races to prefetch: " + str(len(tasks)))
        sem = asyncio.Semaphore(CONCURRENCY)
        done = 0
        ok = 0
        skip = 0
        fail = 0
        t0 = time.time()
        for (d, tc, sc, rn, detail) in tasks:
            rid = "nar-" + d + "-" + str(tc) + "-" + str(rn)
            if not force:
                cached, _ = entry_store.get(rid)
                if cached:
                    skip += 1
                    continue
            payload = await _fetch_ent1(client, sem, d, tc, sc, rn)
            done += 1
            if payload and payload.get("runners"):
                payload["start_hhmm"] = (detail or {}).get("start_hhmm")
                payload["distance"] = (detail or {}).get("distance", 0)
                payload["surface"] = (detail or {}).get("surface", "ダート")
                entry_store.upsert(rid, d[:4] + "-" + d[4:6] + "-" + d[6:8], payload)
                ok += 1
            else:
                fail += 1
            if done % 20 == 0:
                rate = done / max(1, time.time() - t0)
                _log("done=" + str(done) + "/" + str(len(tasks))
                     + " ok=" + str(ok) + " skip=" + str(skip) + " fail=" + str(fail)
                     + " rate=" + str(round(rate, 2)) + "/s")
    _log("DONE ok=" + str(ok) + " skip=" + str(skip) + " fail=" + str(fail))
    _log("entry cache count=" + str(entry_store.count()))


if __name__ == "__main__":
    days = 7
    force = False
    for a in sys.argv[1:]:
        if a == "force":
            force = True
        elif a.isdigit():
            days = int(a)
    asyncio.run(main_async(days, force))
import os as _o
_o._exit(0)
