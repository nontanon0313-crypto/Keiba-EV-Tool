"""既存 scraped_races の ent1 を再取得して:
  A) 馬マスタ horses を構築
  B) scraped_races.runners に lineage_nb / age_sex を書き戻す

同じ ent1 取得で両方行うため、二度手間を避ける。

使い方:
    python3 -m backend.scripts.build_horse_master
    python3 -m backend.scripts.build_horse_master 100
"""
import os
import sys
import json
import asyncio
import time
import re
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

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
            try:
                num = int(cells[2].get_text(strip=True))
            except (ValueError, IndexError):
                continue
            name_cell = cells[5]
        elif len(cells) >= 12:
            try:
                num = int(cells[0].get_text(strip=True))
            except (ValueError, IndexError):
                continue
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
        out.append({"horse_number": num, "lineage_nb": ln, "name": nm, "age_sex": age_sex})
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
        r = c.execute("SELECT race_id, payload FROM scraped_races ORDER BY race_id")
        races = []
        for row in r.rows:
            try:
                d = json.loads(row[1]) if isinstance(row[1], str) else row[1]
                races.append({"race_id": row[0], "payload": d})
            except Exception:
                continue
    finally:
        try:
            c.close()
        except Exception:
            pass
    if limit:
        races = races[:int(limit)]
    _log("races to process: " + str(len(races)))

    sem = asyncio.Semaphore(CONCURRENCY)
    seen_horses = set()
    horse_buf = []
    total_horses = 0
    updated_races = 0
    t0 = time.time()

    async with httpx.AsyncClient(headers=HEADERS) as client:
        tasks = []
        for race in races:
            d = race["payload"]
            date = str(d.get("date", "")).replace("-", "")
            if not date:
                continue
            tasks.append((race, _fetch_ent1(client, sem, date, d.get("track_cd"), d.get("sponsor_cd"), d.get("race_nb"))))
        done = 0
        for (race, coro) in tasks:
            horses = await coro
            done += 1
            if not horses:
                continue
            by_num = {hh["horse_number"]: hh for hh in horses}
            runners = race["payload"].get("runners") or []
            changed = False
            for run in runners:
                num = run.get("horse_number")
                hh = by_num.get(num)
                if not hh:
                    continue
                if run.get("horse_id") != hh["lineage_nb"] or run.get("age_sex") != hh["age_sex"]:
                    run["horse_id"] = hh["lineage_nb"]
                    run["age_sex"] = hh["age_sex"]
                    changed = True
                if hh["lineage_nb"] not in seen_horses:
                    seen_horses.add(hh["lineage_nb"])
                    horse_buf.append({"lineage_nb": hh["lineage_nb"], "name": hh["name"], "age_sex": hh["age_sex"], "affiliation": ""})
                    total_horses += 1
            if changed:
                race["payload"]["runners"] = runners
                race["_dirty"] = True
                updated_races += 1
            if len(horse_buf) >= 200:
                horse_store.upsert_many(horse_buf)
                horse_buf = []
            # 進捗
            if done % 100 == 0:
                rate = done / max(1, time.time() - t0)
                _log("done=" + str(done) + "/" + str(len(tasks))
                     + " horses=" + str(total_horses)
                     + " updated_races=" + str(updated_races)
                     + " rate=" + str(round(rate, 2)) + "/s")
        if horse_buf:
            horse_store.upsert_many(horse_buf)

        # scraped_races を書き戻し
        dirty = [r for r in races if r.get("_dirty")]
        _log("writing back " + str(len(dirty)) + " races")
        c2 = libsql_client.create_client_sync(url=h, auth_token=token)
        try:
            for i, race in enumerate(dirty, 1):
                payload = dict(race["payload"])
                payload.pop("_dirty", None)
                pj = json.dumps(payload, ensure_ascii=False)
                try:
                    c2.execute("UPDATE scraped_races SET payload=? WHERE race_id=?", [pj, race["race_id"]])
                except Exception as e:
                    _log("update fail " + race["race_id"] + ": " + str(e))
                if i % 200 == 0:
                    _log("written " + str(i) + "/" + str(len(dirty)))
        finally:
            try:
                c2.close()
            except Exception:
                pass
    _log("DONE horses=" + str(total_horses) + " updated_races=" + str(updated_races))
    _log("master count=" + str(horse_store.count()))


if __name__ == "__main__":
    lim = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].isdigit() else None
    asyncio.run(main_async(lim))
import os as _o
_o._exit(0)
