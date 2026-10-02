"""全レース×全馬の特徴量を計算して features テーブルに保存する。

中断再開可能: 既に features があるレースはスキップ。
使い方:
    python3 -m backend.scripts.build_features
    python3 -m backend.scripts.build_features limit=100
"""
import os
import sys
import json
import time
from datetime import datetime, date as date_cls

import libsql_client

from backend.app.services import horse_detail_store, feature_store
from backend.app.services.horse_features import extract_features

LOG_PATH = "features.log"
BATCH_RACES = 50


def _log(msg):
    line = "[" + datetime.now().strftime("%H:%M:%S") + "] " + msg
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def main(limit=None):
    url = os.getenv("TURSO_URL")
    token = os.getenv("TURSO_TOKEN")
    if not url or not token:
        _log("TURSO_URL/TURSO_TOKEN not set")
        return
    h = url.replace("libsql://", "https://").replace("wss://", "https://")
    c = libsql_client.create_client_sync(url=h, auth_token=token)
    try:
        done_races = feature_store.races_done()
        _log("already computed: " + str(len(done_races)) + " races")
        r = c.execute("SELECT race_id, payload FROM scraped_races ORDER BY race_id")
        races = []
        for row in r.rows:
            rid = row[0]
            if rid in done_races:
                continue
            try:
                d = json.loads(row[1]) if isinstance(row[1], str) else row[1]
                races.append((rid, d))
            except Exception:
                continue
    finally:
        try:
            c.close()
        except Exception:
            pass
    if limit:
        races = races[:int(limit)]
    _log("races to compute: " + str(len(races)))

    t0 = time.time()
    total_rows = 0
    total_races = 0
    buf = []
    for bi in range(0, len(races), BATCH_RACES):
        batch = races[bi:bi+BATCH_RACES]
        # 必要 lineage_nb を集める
        all_ln = []
        for rid, d in batch:
            for run in (d.get("runners") or []):
                ln = run.get("horse_id")
                if ln:
                    all_ln.append(ln)
        # 一括取得
        try:
            details_map = horse_detail_store.get_many(all_ln)
        except Exception as exc:
            _log("get_many fail: " + repr(exc))
            details_map = {}
        for rid, d in batch:
            race_date = _parse_date(d.get("date"))
            if race_date is None:
                continue
            race_info = {
                "distance": d.get("distance"),
                "track_condition": d.get("track_condition"),
                "venue": d.get("venue"),
                "surface": d.get("surface"),
                "race_name": d.get("race_name"),
            }
            for run in (d.get("runners") or []):
                num = run.get("horse_number")
                ln = run.get("horse_id")
                if not num:
                    continue
                payload = details_map.get(ln) if ln else None
                feats = extract_features(payload, race_date, race_info)
                # runners 側の属性も加える
                feats["weight"] = run.get("weight")
                feats["frame"] = run.get("frame_number")
                feats["age_sex"] = run.get("age_sex")
                feats["jockey"] = run.get("jockey")
                feats["odds_win"] = run.get("odds_win")
                feats["popularity"] = run.get("popularity")
                feats["horse_weight"] = run.get("horse_weight")
                buf.append((rid, num, ln or "", feats))
        # バッチ保存
        try:
            n = feature_store.upsert_batch(buf)
            total_rows += n
            total_races += len(batch)
        except Exception as exc:
            _log("upsert fail: " + repr(exc))
        buf = []
        elapsed = time.time() - t0
        done = min(bi + BATCH_RACES, len(races))
        rate = done / elapsed if elapsed > 0 else 0
        eta = (len(races) - done) / rate if rate > 0 else 0
        _log(f"  {done}/{len(races)} rows={total_rows} elapsed={elapsed:.0f}s eta={eta:.0f}s")
    _log("DONE rows=" + str(total_rows) + " races=" + str(total_races))
    _log("feature count=" + str(feature_store.count()))


if __name__ == "__main__":
    lim = None
    for a in sys.argv[1:]:
        if a.startswith("limit="):
            lim = a.split("=", 1)[1]
    main(lim)
import os as _o
_o._exit(0)
