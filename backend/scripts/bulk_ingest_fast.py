"""bulk_ingest 並列版。asyncio + セマフォで並列度制御。"""
import os
import sys
import asyncio
import time
from datetime import datetime, timedelta

import httpx

from backend.app.services import race_store, odds_store

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Mobile Safari/537.36",
}
CONCURRENCY = 8  # 並列度
SLEEP = 0.5  # 各リクエスト後の待機


async def fetch_json(client, url, retries=3):
    for attempt in range(retries):
        try:
            r = await client.get(url, timeout=20, follow_redirects=True)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (400, 429, 500, 502, 503):
                await asyncio.sleep(3 * (attempt + 1))
                continue
            return None
        except Exception:
            await asyncio.sleep(3 * (attempt + 1))
    return None


async def fetch_race_list(client, date):
    url = f"https://race.netkeiba.com/top/race_list_sub.html?kaisai_date={date}"
    try:
        r = await client.get(url, timeout=20, follow_redirects=True)
        if r.status_code != 200:
            return []
        import re
        ids = set(re.findall(r"race_id=(\d{12})", r.text))
        return sorted(ids)
    except Exception:
        return []


async def fetch_result_async(client, race_id):
    url = f"https://db.netkeiba.com/race/{race_id}/"
    for attempt in range(3):
        try:
            r = await client.get(url, timeout=20, follow_redirects=True)
            if r.status_code == 200:
                return r.text
            if r.status_code in (400, 429, 500, 502, 503):
                await asyncio.sleep(3 * (attempt + 1))
                continue
            return None
        except Exception:
            await asyncio.sleep(3 * (attempt + 1))
    return None


async def fetch_odds_json(client, race_id, t):
    url = "https://race.netkeiba.com/api/api_get_jra_odds.html"
    params = {"race_id": race_id, "type": t, "action": "update", "sort": "1"}
    for attempt in range(3):
        try:
            r = await client.get(url, params=params, timeout=15, follow_redirects=True)
            if r.status_code == 200:
                return r.json()
            await asyncio.sleep(2 * (attempt + 1))
        except Exception:
            await asyncio.sleep(2 * (attempt + 1))
    return None


def parse_result_html(html, race_id):
    """netkeiba 結果ページから結果と出走馬を取得。既存netkeiba.fetch_race_resultと同じ。"""
    from backend.app.services.scraper import netkeiba
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    name_el = soup.select_one(".RaceName")
    race_name = name_el.get_text(strip=True) if name_el else ""
    surface = ""
    distance = 0
    info_text = ""
    for sel in [".RaceData01", ".RaceData", ".racedata"]:
        el = soup.select_one(sel)
        if el:
            info_text = el.get_text(" ", strip=True)
            break
    import re
    if info_text:
        m = re.search(r"(芝|ダ|障)\s*(\d{3,4})m", info_text)
        if m:
            surface = {"芝": "芝", "ダ": "ダート", "障": "障害"}.get(m.group(1), "")
            distance = int(m.group(2))
    table = soup.select_one("table.ResultsByRaceDetail")
    if table is None:
        return None
    rows = table.find_all("tr")
    runners = []
    finish_order = []
    for row in rows[1:]:
        tds = row.find_all("td")
        if len(tds) < 18:
            continue
        try:
            finish = int(tds[0].get_text(strip=True)) if tds[0].get_text(strip=True).isdigit() else None
        except Exception:
            finish = None
        try:
            frame = int(tds[1].get_text(strip=True)) or 0
        except Exception:
            frame = 0
        try:
            num = int(tds[2].get_text(strip=True))
        except Exception:
            continue
        name_a = tds[3].find("a")
        horse_name = name_a.get_text(strip=True) if name_a else tds[3].get_text(strip=True)
        try:
            weight = float(re.sub(r"[^\d.]", "", tds[5].get_text(strip=True)) or 0)
        except Exception:
            weight = 0.0
        jockey = tds[6].get_text(strip=True)
        try:
            odds_txt = tds[16].get_text(strip=True)
            odds_win = float(odds_txt) if odds_txt and odds_txt != "--" else None
        except Exception:
            odds_win = None
        try:
            pop_txt = tds[17].get_text(strip=True)
            popularity = int(pop_txt) if pop_txt.isdigit() else None
        except Exception:
            popularity = None
        runners.append({
            "horse_number": num, "frame_number": frame,
            "horse_name": horse_name, "jockey": jockey,
            "weight": weight, "odds_win": odds_win,
            "popularity": popularity, "finish": finish,
        })
        if finish is not None and finish <= 3:
            finish_order.append((finish, num))
    finish_order.sort()
    return {
        "race_id": race_id, "race_name": race_name,
        "surface": surface, "distance": distance,
        "runners": runners,
        "finish_order": [n for _, n in finish_order],
    }


async def process_race(client, sem, rid, existing_races, existing_odds, stats):
    async with sem:
        # 結果
        if rid not in existing_races:
            html = await fetch_result_async(client, rid)
            if html:
                data = parse_result_html(html, rid)
                if data and data.get("finish_order"):
                    race_store.save_race(rid, data)
                    existing_races.add(rid)
                    stats["races"] += 1
            await asyncio.sleep(SLEEP)
        # オッズ: 券種を並列取得
        if rid not in existing_odds:
            cur = odds_store.get_odds(rid) or {}
            tmap = {"1":"win","2":"place","4":"quinella","5":"wide","6":"exacta","7":"trio","8":"trifecta"}
            need = [t for t in tmap if not cur.get(tmap[t])]
            if need:
                results = await asyncio.gather(*[fetch_odds_json(client, rid, t) for t in need], return_exceptions=True)
                merged = dict(cur)
                for t, data in zip(need, results):
                    if not data or isinstance(data, Exception):
                        continue
                    odds_map = (data.get("data") or {}).get("odds") or {}
                    inner = odds_map.get(t) or {}
                    result = {}
                    for key, arr in inner.items():
                        if not isinstance(arr, list) or not arr:
                            continue
                        n = len(key) // 2
                        parts = [str(int(key[i*2:i*2+2])) for i in range(n)]
                        combo = "-".join(parts)
                        try:
                            v = float(str(arr[0]).replace(",", ""))
                            if v <= 0:
                                continue
                        except Exception:
                            continue
                        ticket = tmap[t]
                        if ticket == "wide" and len(arr) >= 2:
                            try:
                                v2 = float(str(arr[1]).replace(",", ""))
                            except Exception:
                                v2 = v
                            result[combo] = {"min": v, "max": v2}
                        else:
                            result[combo] = {"odds": v}
                    if result:
                        merged[ticket] = result
                if merged:
                    odds_store.save_odds(rid, merged)
                    existing_odds.add(rid)
                    stats["odds"] += 1


async def main_async(date_from, date_to, sleep_sec):
    global SLEEP
    SLEEP = sleep_sec
    existing_races = set(race_store.list_race_ids())
    existing_odds = set(odds_store.list_race_ids())
    print(f"[fast] existing races={len(existing_races)} odds={len(existing_odds)}", flush=True)

    sem = asyncio.Semaphore(CONCURRENCY)
    stats = {"races": 0, "odds": 0}
    t0 = time.time()

    d0 = datetime.strptime(date_from, "%Y-%m-%d")
    d1 = datetime.strptime(date_to, "%Y-%m-%d")
    async with httpx.AsyncClient(headers=HEADERS) as client:
        d = d0
        while d <= d1:
            date_str = d.strftime("%Y%m%d")
            ids = await fetch_race_list(client, date_str)
            todo = [rid for rid in ids if rid not in existing_races or rid not in existing_odds]
            print(f"[{date_str}] {len(ids)} races, {len(todo)} todo", flush=True)
            tasks = [process_race(client, sem, rid, existing_races, existing_odds, stats) for rid in todo]
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
                elapsed = time.time() - t0
                print(f"  [progress] races={stats['races']} odds={stats['odds']} elapsed={elapsed:.0f}s", flush=True)
            d += timedelta(days=1)
    print(f"[fast] done races={stats['races']} odds={stats['odds']}", flush=True)
    os._exit(0)


def main():
    date_from = sys.argv[1] if len(sys.argv) > 1 else "2025-04-01"
    date_to = sys.argv[2] if len(sys.argv) > 2 else "2025-12-31"
    sleep_sec = float(sys.argv[3]) if len(sys.argv) > 3 else 0.5
    asyncio.run(main_async(date_from, date_to, sleep_sec))


if __name__ == "__main__":
    main()
