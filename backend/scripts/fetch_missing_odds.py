"""オッズ未取得レースのオッズを並列取得。"""
import os
import sys
import asyncio
import time

import httpx

from backend.app.services import race_store, odds_store

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Mobile Safari/537.36",
}
CONCURRENCY = 10
TICKETS = {"1":"win","2":"place","4":"quinella","5":"wide","6":"exacta","7":"trio","8":"trifecta"}


async def fetch_odds_json(client, race_id, t, retries=3):
    url = "https://race.netkeiba.com/api/api_get_jra_odds.html"
    params = {"race_id": race_id, "type": t, "action": "update", "sort": "1"}
    for attempt in range(retries):
        try:
            r = await client.get(url, params=params, timeout=15, follow_redirects=True)
            if r.status_code == 200:
                return r.json()
            await asyncio.sleep(2 * (attempt + 1))
        except Exception:
            await asyncio.sleep(2 * (attempt + 1))
    return None


async def process(client, sem, rid, stats):
    async with sem:
        results = await asyncio.gather(
            *[fetch_odds_json(client, rid, t) for t in TICKETS],
            return_exceptions=True,
        )
        merged = {}
        for t, data in zip(TICKETS.keys(), results):
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
                ticket = TICKETS[t]
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
            stats["ok"] += 1
        else:
            stats["fail"] += 1
        if stats["ok"] + stats["fail"] % 100 == 0:
            print(f"  progress ok={stats['ok']} fail={stats['fail']}", flush=True)


async def main_async():
    races = set(race_store.list_race_ids())
    odds = set(odds_store.list_race_ids())
    missing = sorted(races - odds)
    print(f"missing odds: {len(missing)}", flush=True)
    if not missing:
        print("nothing to fetch", flush=True)
        os._exit(0)
    sem = asyncio.Semaphore(CONCURRENCY)
    stats = {"ok": 0, "fail": 0}
    t0 = time.time()
    async with httpx.AsyncClient(headers=HEADERS) as client:
        tasks = []
        for rid in missing:
            tasks.append(process(client, sem, rid, stats))
        await asyncio.gather(*tasks, return_exceptions=True)
    print(f"done ok={stats['ok']} fail={stats['fail']} in {time.time()-t0:.0f}s", flush=True)
    os._exit(0)


if __name__ == "__main__":
    asyncio.run(main_async())
