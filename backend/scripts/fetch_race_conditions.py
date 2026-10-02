"""全レースの天候・馬場を並列取得して payload に追加。

改良点:
- HTTP は並列16
- Turso への書き戻しはチャンク単位で batch 実行
- 中断再開可能（weather が既に入っているレースはスキップ）
"""
import os
import json
import re
import time
import asyncio
import httpx
import libsql_client

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Mobile Safari/537.36",
    "Referer": "https://www.oddspark.com/keiba/",
}

WEATHER_MAP = {"1": "晴", "2": "曇", "3": "不明", "4": "雨"}
BABA_MAP = {"1": "良", "2": "稍重", "3": "重", "4": "不良"}
EXCLUDED_TRACK_CODES = ("03",)
CONCURRENCY = 16
CHUNK_SIZE = 200


def parse_race_condition(html):
    m1 = re.search(r"ico-tenki-(\d+)\.gif", html)
    m2 = re.search(r"ico-baba-(\d+)\.gif", html)
    weather = WEATHER_MAP.get(m1.group(1), "不明") if m1 else "不明"
    baba = BABA_MAP.get(m2.group(1), "不明") if m2 else "不明"
    return weather, baba


async def _fetch_one(client, sem, rid, date, track_cd, sponsor_cd, race_nb):
    url = (f"https://www.oddspark.com/keiba/RaceResult.do"
           f"?sponsorCd={sponsor_cd}&raceDy={date}"
           f"&opTrackCd={track_cd}&raceNb={race_nb}")
    async with sem:
        try:
            r = await client.get(url, timeout=25, follow_redirects=True)
            if r.status_code != 200:
                return rid, None, None
            weather, baba = parse_race_condition(r.text)
            return rid, weather, baba
        except Exception:
            return rid, None, None


async def fetch_chunk(targets):
    sem = asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True) as client:
        coros = [
            _fetch_one(client, sem, rid, date, tc, sc, rn)
            for (rid, date, tc, sc, rn) in targets
        ]
        return await asyncio.gather(*coros, return_exceptions=True)


def main():
    url = os.getenv("TURSO_URL")
    token = os.getenv("TURSO_TOKEN")
    http_url = url.replace("libsql://", "https://").replace("wss://", "https://")
    client = libsql_client.create_client_sync(url=http_url, auth_token=token)

    r = client.execute("SELECT race_id, payload FROM scraped_races ORDER BY race_id")
    rows = list(r.rows)
    print(f"全レース: {len(rows)}", flush=True)

    targets = []
    payload_map = {}
    n_skipped_exist = 0
    n_skipped_excl = 0
    for row in rows:
        rid = row[0]
        parts = rid.split("-")
        if len(parts) >= 3 and parts[2] in EXCLUDED_TRACK_CODES:
            n_skipped_excl += 1
            continue
        try:
            payload = json.loads(row[1]) if isinstance(row[1], str) else row[1]
        except Exception:
            continue
        if payload.get("weather") and payload.get("track_condition"):
            n_skipped_exist += 1
            continue
        date = payload.get("date", "").replace("-", "")
        targets.append((rid, date, payload.get("track_cd", ""),
                        payload.get("sponsor_cd", ""), payload.get("race_nb", 0)))
        payload_map[rid] = payload

    print(f"対象: {len(targets)} (skipped_exist={n_skipped_exist} excl={n_skipped_excl})", flush=True)

    t0 = time.time()
    n_updated = 0
    n_failed = 0
    total = len(targets)

    for chunk_start in range(0, total, CHUNK_SIZE):
        chunk = targets[chunk_start:chunk_start + CHUNK_SIZE]
        try:
            results = asyncio.run(fetch_chunk(chunk))
        except Exception as exc:
            print(f"  chunk gather fail: {exc!r}", flush=True)
            results = []
        stmts = []
        for res in results:
            if isinstance(res, Exception) or not isinstance(res, tuple) or len(res) != 3:
                n_failed += 1
                continue
            rid, weather, baba = res
            if weather is None:
                n_failed += 1
                continue
            p = payload_map.get(rid)
            if not p:
                n_failed += 1
                continue
            p["weather"] = weather
            p["track_condition"] = baba
            new_payload = json.dumps(p, ensure_ascii=False)
            stmts.append(("UPDATE scraped_races SET payload=? WHERE race_id=?", [new_payload, rid]))
        if stmts:
            try:
                client.batch(stmts)
                n_updated += len(stmts)
            except Exception as exc:
                print(f"  batch update fail: {exc!r}", flush=True)
                n_failed += len(stmts)
        elapsed = time.time() - t0
        done = min(chunk_start + CHUNK_SIZE, total)
        rate = done / elapsed if elapsed > 0 else 0
        eta = (total - done) / rate if rate > 0 else 0
        print(f"  {done}/{total} updated={n_updated} failed={n_failed} "
              f"elapsed={elapsed:.0f}s eta={eta:.0f}s", flush=True)

    print(f"\n=== 完了: updated={n_updated} failed={n_failed} "
          f"elapsed={time.time()-t0:.0f}s ===", flush=True)

    try:
        client.close()
    except Exception:
        pass


if __name__ == "__main__":
    main()
import os as _o
_o._exit(0)
