"""既存 scraped_races の ent1 を再取得して馬マスタを構築する。

使い方:
    python3 -m backend.scripts.build_horse_master
    python3 -m backend.scripts.build_horse_master 100    # 先頭100レースだけ(テスト)
"""
import os
import sys
import asyncio
import time
from datetime import datetime

import httpx
from bs4 import BeautifulSoup
import re

from backend.app.services import horse_store

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Mobile Safari/537.36",
    "Referer": "https://www.oddspark.com/keiba/",
}
BASE = "https://www.oddspark.com"
CONCURRENCY = 12
LOG_PATH = "horse_master.log"


def _log(msg):
    line = "[" + datetime.now().strftime("%H:%M:%S") + "] " + msg
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


async def _fetch_ent1(client, sem, date, track_cd, sponsor_cd, race_nb):
    url = (BASE + "/keiba/RaceList.do?raceDy=" + str(date)
           + "&opTrackCd=" + str(track_cd)
           + "&sponsorCd=" + str(sponsor_cd)
           + "&raceNb=" + str(race_nb))
    async with sem:
        try:
            r = await client.get(url, timeout=20, follow_redirects=True)
            if r.status_code != 200:
                return []
            html = r.text
        except Exception:
            return []
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.ent1")
    if table is None:
        return []
    out = []
    for row in table.find_all("tr"):
        cells = row.find_all(["td", "th"])
        if len(cells) >= 16:
            name_cell = cells[5]
        elif len(cells) >= 12:
            name_cell = cells[3]
        else:
            continue
        a = name_cell.find("a", href=re.compile(r"lineageNb="))
        if not a:
            continue
        m = re.search(r"lineageNb=(\d+)", a.get("href", ""))
        if not m:
            continue
        ln = m.group(1)
        nm = a.get_text(strip=True)
        if not nm:
            continue
        full_txt = name_cell.get_text(" ", strip=True)
        m2 = re.search(r"[牡牝セ]\s*\d+", full_txt)
        age_sex = re.sub(r"\s+", "", m2.group(0)) if m2 else ""
        out.append({"lineage_nb": ln, "name": nm, "age_sex": age_sex, "affiliation": ""})
    return out


async def main_async(limit=None):
    import libsql_client
    url = os.getenv("TURSO_URL")
    token = os.getenv("TURSO_TOKEN")
    if not url or not token:
        _log("TURSO_URL/TURSO_TOKEN not set")
        return
    h = url.replace("libsql://", "https://").replace("wss://", "https://")
    c = libsql_client.create_client_sync(url=h, auth_token=token)
    try:
        r = c.execute("SELECT payload FROM scraped_races ORDER BY race_id")
        races = []
        for row in r.rows:
            import json
            try:
                d = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                races.append((d.get("date"), d.get("track_cd"), d.get("sponsor_cd"), d.get("race_nb")))
            except Exception:
                continue
    finally:
        try:
            c.close()
        except Exception:
            pass
    if limit:
        races = races[:int(limit)]
    _log("races to fetch: " + str(len(races)))

    sem = asyncio.Semaphore(CONCURRENCY)
    total_horses = 0
    seen = set()
    buf = []
    async with httpx.AsyncClient(headers=HEADERS) as client:
        tasks = []
        for (date, tc, sc, rn) in races:
            if not date:
                continue
            d = str(date).replace("-", "")
            tasks.append(_fetch_ent1(client, sem, d, tc, sc, rn))
        t0 = time.time()
        done = 0
        for coro in asyncio.as_completed(tasks):
            horses = await coro
            done += 1
            for hh in horses:
                if hh["lineage_nb"] in seen:
                    continue
                seen.add(hh["lineage_nb"])
                buf.append(hh)
                total_horses += 1
            if len(buf) >= 200:
                horse_store.upsert_many(buf)
                buf = []
            if done % 200 == 0:
                rate = done / max(1, time.time() - t0)
                _log("done=" + str(done) + "/" + str(len(tasks))
                     + " horses=" + str(total_horses)
                     + " rate=" + str(round(rate, 2)) + "/s")
        if buf:
            horse_store.upsert_many(buf)
    _log("DONE total horses=" + str(total_horses))
    _log("master count=" + str(horse_store.count()))


if __name__ == "__main__":
    lim = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(main_async(lim))
import os as _o
_o._exit(0)
