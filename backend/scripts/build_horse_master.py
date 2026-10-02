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
CONCURRENCY = 32
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
                return [], ""
            html = r.text
        except Exception:
            return [], ""
    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.find("title")
    race_name = title_el.get_text(strip=True) if title_el else ""
    table = soup.select_one("table.ent1")
    if table is None:
        return [], race_name
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
        # 騎手・斤量
        jockey = ""
        weight_val = None
        trainer = ""
        if len(cells) >= 16:
            jw_cell = cells[6]
            w_cell = cells[8]
        else:
            jw_cell = cells[4]
            w_cell = cells[6]
        jw_txt = jw_cell.get_text(" ", strip=True)
        mj = re.match(r"([^\d]+)", jw_txt)
        if mj:
            jockey = mj.group(1).strip()
        mw = re.search(r"(\d+\.?\d*)", jw_txt)
        if mw:
            try:
                weight_val = float(mw.group(1))
            except Exception:
                weight_val = None
        # 馬体重と増減
        horse_weight = None
        hw_change = None
        w_txt = w_cell.get_text(" ", strip=True)
        mhw = re.search(r"(\d+)\s*[（(]?([+-]?\d+)?", w_txt)
        if mhw:
            try:
                horse_weight = int(mhw.group(1))
            except Exception:
                horse_weight = None
            if mhw.group(2):
                try:
                    hw_change = int(mhw.group(2))
                except Exception:
                    hw_change = None
        out.append({
            "horse_number": num, "lineage_nb": ln, "name": nm, "age_sex": age_sex,
            "jockey": jockey, "weight": weight_val, "trainer": trainer,
            "horse_weight": horse_weight, "horse_weight_change": hw_change,
        })
    return out, race_name


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
        jobs = []
        for race in races:
            d = race["payload"]
            date = str(d.get("date", "")).replace("-", "")
            if not date:
                continue
            # 既に race_name と runner の horse_id が入っているレースはスキップ（中断再開用）
            runners = d.get("runners") or []
            already = bool(d.get("race_name")) and all(
                (run.get("horse_id") and run.get("age_sex") and run.get("trainer"))
                for run in runners
            ) if runners else False
            if already:
                continue
            jobs.append((race, date, d.get("track_cd"), d.get("sponsor_cd"), d.get("race_nb")))
        _log("jobs: " + str(len(jobs)))

        wb_client = libsql_client.create_client_sync(url=h, auth_token=token)
        BATCH = 32
        done = 0
        for bi in range(0, len(jobs), BATCH):
            batch = jobs[bi:bi+BATCH]
            coros = [_fetch_ent1(client, sem, date, tc, sc, rn) for (_, date, tc, sc, rn) in batch]
            try:
                results = await asyncio.gather(*coros, return_exceptions=True)
            except Exception as exc:
                print("[batch] gather fail: " + repr(exc), flush=True)
                results = [None] * len(batch)
            for res, (race, date, tc, sc, rn) in zip(results, batch):
                done += 1
                if isinstance(res, Exception) or not isinstance(res, tuple) or len(res) != 2:
                    continue
                horses, race_name = res
                runners = race["payload"].get("runners") or []
                changed = False
                if race_name and race["payload"].get("race_name") != race_name:
                    race["payload"]["race_name"] = race_name
                    changed = True
                if horses:
                    by_num = {hh["horse_number"]: hh for hh in horses}
                    for run in runners:
                        num = run.get("horse_number")
                        hh = by_num.get(num)
                        if not hh:
                            continue
                        if run.get("horse_id") != hh["lineage_nb"]:
                            run["horse_id"] = hh["lineage_nb"]; changed = True
                        if run.get("age_sex") != hh["age_sex"]:
                            run["age_sex"] = hh["age_sex"]; changed = True
                        if hh.get("weight") and run.get("weight") != hh["weight"]:
                            run["weight"] = hh["weight"]; changed = True
                        if run.get("horse_weight_change") is None and hh.get("horse_weight_change") is not None:
                            run["horse_weight_change"] = hh["horse_weight_change"]; changed = True
                        if hh["lineage_nb"] not in seen_horses:
                            seen_horses.add(hh["lineage_nb"])
                            horse_buf.append({"lineage_nb": hh["lineage_nb"], "name": hh["name"], "age_sex": hh["age_sex"], "affiliation": ""})
                            total_horses += 1
                if runners:
                    rr_by_num = {}
                    for rr in (race["payload"].get("result_runners") or []):
                        rn2 = rr.get("horse_number")
                        if rn2 and rr.get("trainer"):
                            rr_by_num[rn2] = rr["trainer"]
                    for run in runners:
                        n2 = run.get("horse_number")
                        if n2 in rr_by_num and not run.get("trainer"):
                            run["trainer"] = rr_by_num[n2]
                            changed = True
                if changed:
                    race["payload"]["runners"] = runners
                    race["_dirty"] = True
                    updated_races += 1
                if len(horse_buf) >= 200:
                    horse_store.upsert_many(horse_buf)
                    horse_buf = []
            rate = done / max(1, time.time() - t0)
            _log("done=" + str(done) + "/" + str(len(jobs))
                 + " horses=" + str(total_horses)
                 + " updated=" + str(updated_races)
                 + " rate=" + str(round(rate, 2)) + "/s")
            # バッチごとに Turso へ書き戻し（中断されても進捗を保持）
            batch_dirty = [item[0] for item in batch if item[0].get("_dirty")]
            if batch_dirty:
                stmts = []
                for race in batch_dirty:
                    payload = dict(race["payload"])
                    payload.pop("_dirty", None)
                    pj = json.dumps(payload, ensure_ascii=False)
                    stmts.append(("UPDATE scraped_races SET payload=? WHERE race_id=?", [pj, race["race_id"]]))
                try:
                    wb_client.batch(stmts)
                except Exception as exc:
                    _log("batch update fail: " + str(exc))
                for race in batch_dirty:
                    race["_dirty"] = False
        if horse_buf:
            horse_store.upsert_many(horse_buf)

    _log("DONE horses=" + str(total_horses) + " updated_races=" + str(updated_races))
    _log("master count=" + str(horse_store.count()))


if __name__ == "__main__":
    lim = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].isdigit() else None
    asyncio.run(main_async(lim))
import os as _o
_o._exit(0)
