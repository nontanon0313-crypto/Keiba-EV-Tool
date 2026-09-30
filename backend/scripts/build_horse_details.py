"""馬マスタの全 lineage_nb について HorseDetail を取得し horse_details に保存する。

使い方:
    python3 -m backend.scripts.build_horse_details         # 未キャッシュのみ
    python3 -m backend.scripts.build_horse_details force   # 全て再取得
    python3 -m backend.scripts.build_horse_details limit=10
"""
import os
import sys
import asyncio
import time
from datetime import datetime

import httpx

from backend.app.services import horse_store, horse_detail_store
from backend.scraper.oddspark_keiba import fetch_horse_detail

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Mobile Safari/537.36",
    "Referer": "https://www.oddspark.com/keiba/",
}
CONCURRENCY = 8
LOG_PATH = "horse_details.log"


def _log(msg):
    line = "[" + datetime.now().strftime("%H:%M:%S") + "] " + msg
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


async def main_async(force=False, limit=None):
    import libsql_client
    url = os.getenv("TURSO_URL")
    token = os.getenv("TURSO_TOKEN")
    if not url or not token:
        _log("TURSO_URL/TURSO_TOKEN not set")
        return
    h = url.replace("libsql://", "https://").replace("wss://", "https://")
    c = libsql_client.create_client_sync(url=h, auth_token=token)
    try:
        r = c.execute("SELECT lineage_nb FROM horses")
        targets = [row[0] for row in r.rows if row[0]]
        cached = set()
        if not force:
            r2 = c.execute("SELECT lineage_nb FROM horse_details")
            cached = set(row[0] for row in r2.rows if row[0])
    finally:
        try:
            c.close()
        except Exception:
            pass
    if not force:
        targets = [t for t in targets if t not in cached]
    if limit:
        targets = targets[:int(limit)]
    _log("targets: " + str(len(targets)) + " (force=" + str(force) + ")")

    sem = asyncio.Semaphore(CONCURRENCY)
    done = 0
    ok = 0
    fail = 0
    t0 = time.time()

    async def one(ln):
        nonlocal done, ok, fail
        async with sem:
            try:
                d = await asyncio.to_thread(fetch_horse_detail, ln)
                if d and d.get("title"):
                    await asyncio.to_thread(horse_detail_store.upsert, ln, d)
                    ok += 1
                else:
                    fail += 1
            except Exception:
                fail += 1
            done += 1
            if done % 50 == 0:
                rate = done / max(1, time.time() - t0)
                _log("done=" + str(done) + "/" + str(len(targets))
                     + " ok=" + str(ok) + " fail=" + str(fail)
                     + " rate=" + str(round(rate, 2)) + "/s")

    await asyncio.gather(*[one(t) for t in targets])
    _log("DONE ok=" + str(ok) + " fail=" + str(fail))
    _log("cache count=" + str(horse_detail_store.count()))


if __name__ == "__main__":
    force = "force" in sys.argv
    lim = None
    for a in sys.argv[1:]:
        if a.startswith("limit="):
            lim = a.split("=", 1)[1]
    asyncio.run(main_async(force, lim))
import os as _o
_o._exit(0)
