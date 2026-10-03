from fastapi import APIRouter, HTTPException
from datetime import datetime
import os
import time
from backend.app.services.race_fetcher import get_races
from backend.app.services import entry_store

router = APIRouter(prefix="/races")


_prefetch_lock = None
_prefetch_state = {"running": False, "date": "", "started_at": "", "last_attempt": 0}


def _ensure_lock():
    global _prefetch_lock
    import threading
    if _prefetch_lock is None:
        _prefetch_lock = threading.Lock()


def _run_prefetch_today():
    """出走表の事前取得を別プロセスで起動する。

    スレッドで動かすとメインスレッドと Turso クライアント (libsql_client) を
    共有してスレッドセーフでなくなり、Render 無料プランで OOM kill される。
    別プロセスにすることで完全に分離する。
    """
    import subprocess
    import sys
    _ensure_lock()
    with _prefetch_lock:
        if _prefetch_state["running"]:
            return
        _prefetch_state["running"] = True
        _prefetch_state["date"] = datetime.now().strftime("%Y%m%d")
        _prefetch_state["started_at"] = datetime.now().isoformat()
        _prefetch_state["last_attempt"] = time.time()
    env = os.environ.copy()
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "backend.scripts.prefetch_entries", "0"],
            cwd=os.getcwd(),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        # 完了を待って running を解除する
        proc.wait()
    except Exception as exc:
        print("[races.prefetch] spawn error: " + repr(exc), flush=True)
    finally:
        with _prefetch_lock:
            _prefetch_state["running"] = False


@router.get("")
def list_races():
    """Turso に保存された実レースのみ返す。"""
    return get_races()


@router.get("/today")
def list_today_races():
    """当日の出走表キャッシュを返す。予想ページ用。
    空の場合、バックグラウンドで自動取得を起動する。"""
    _ensure_lock()
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        entries = entry_store.list_by_date(today)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="entry store error: " + repr(exc))

    started = False
    if not entries:
        with _prefetch_lock:
            # 10分以内に試行済みなら再起動しない（リトライ連打で連続起動するのを防ぐ）
            cooldown_ok = (time.time() - _prefetch_state.get("last_attempt", 0)) > 600
            if not _prefetch_state["running"] and cooldown_ok:
                started = True
        if started:
            import threading
            t = threading.Thread(target=_run_prefetch_today, daemon=True)
            t.start()

    out = []
    for entry in entries:
        payload = entry.get("payload") or {}
        rid = entry.get("race_id") or ""
        parts = rid.split("-")
        date_compact = parts[1] if len(parts) > 1 else ""
        track_cd = parts[2] if len(parts) > 2 else ""
        race_nb = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
        start_hhmm = payload.get("start_hhmm") or "00:00"
        start_iso = ""
        if len(date_compact) == 8:
            start_iso = (date_compact[:4] + "-" + date_compact[4:6] + "-"
                         + date_compact[6:8] + "T" + start_hhmm + ":00")
        out.append({
            "race_id": rid,
            "date": today,
            "track_cd": track_cd,
            "race_nb": race_nb,
            "race_number": race_nb,
            "venue": _venue_name(track_cd),
            "surface": payload.get("surface", "ダート"),
            "distance": payload.get("distance", 0),
            "start_at": start_iso,
            "start_hhmm": start_hhmm,
            "runners": payload.get("runners", []),
            "source": "prefetched",
        })
    out.sort(key=lambda x: (x["venue"] or "", x["race_nb"]))
    with _prefetch_lock:
        running = _prefetch_state["running"]
    return {
        "date": today,
        "races": out,
        "prefetch": {
            "running": running,
            "started_this_call": started,
        },
    }


def _venue_name(track_cd):
    from backend.constants import TRACK_CD_TO_VENUE
    return TRACK_CD_TO_VENUE.get(str(track_cd), "")


@router.get("/search")
def search_races(date_from: str = "", date_to: str = "", venue: str = "", limit: int = 200):
    """過去レースを検索する。日付範囲・会場で絞り込み。"""
    import os, json
    import libsql_client
    url = os.getenv("TURSO_URL")
    token = os.getenv("TURSO_TOKEN")
    if not url or not token:
        raise HTTPException(500, "TURSO not set")
    h = url.replace("libsql://", "https://").replace("wss://", "https://")
    c = libsql_client.create_client_sync(url=h, auth_token=token)
    try:
        where = ["race_id LIKE 'nar-%'"]
        args = []
        if date_from:
            df = date_from.replace("-", "")
            where.append("race_id >= ?")
            args.append("nar-" + df + "-00-0")
        if date_to:
            dt = date_to.replace("-", "")
            where.append("race_id <= ?")
            args.append("nar-" + dt + "-99-99")
        sql = "SELECT race_id, payload FROM scraped_races WHERE " + " AND ".join(where) + " ORDER BY race_id LIMIT ?"
        args.append(int(limit))
        r = c.execute(sql, args)
        rows = list(r.rows)
        out = []
        for row in rows:
            try:
                d = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            except Exception:
                continue
            v = (d.get("venue") or "").strip()
            if venue and v != venue:
                continue
            out.append({
                "race_id": row[0],
                "date": d.get("date"),
                "venue": v,
                "race_number": d.get("race_number"),
                "surface": d.get("surface"),
                "distance": d.get("distance"),
                "start_at": d.get("start_at"),
                "n_runners": len(d.get("runners") or []),
                "has_result": bool(d.get("finish_order")),
            })
        return {"races": out, "count": len(out)}
    finally:
        try:
            c.close()
        except Exception:
            pass


@router.get("/venues")
def list_venues():
    """利用可能な会場一覧を返す。"""
    from backend.constants import TRACK_CD_TO_VENUE
    return {"venues": sorted(set(TRACK_CD_TO_VENUE.values()))}

@router.get("/{race_id}")
def get_race(race_id: str):
    for r in get_races():
        if r.race_id == race_id:
            return r
    # 過去レース: scraped_races を参照
    import os, json
    import libsql_client
    url = os.getenv("TURSO_URL")
    token = os.getenv("TURSO_TOKEN")
    if url and token:
        h = url.replace("libsql://", "https://").replace("wss://", "https://")
        c = libsql_client.create_client_sync(url=h, auth_token=token)
        try:
            r2 = c.execute("SELECT payload FROM scraped_races WHERE race_id=?", [race_id])
            if r2.rows:
                d = json.loads(r2.rows[0][0])
                return d
        except Exception as exc:
            print("[races.detail] scraped lookup error: " + repr(exc), flush=True)
        finally:
            try:
                c.close()
            except Exception:
                pass
    try:
        payload, _scraped_at = entry_store.get(race_id)
        if payload:
            parts = race_id.split("-")
            date_compact = parts[1] if len(parts) > 1 else ""
            track_cd = parts[2] if len(parts) > 2 else ""
            race_nb = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
            start_hhmm = payload.get("start_hhmm") or "00:00"
            date_iso = ""
            if len(date_compact) == 8:
                date_iso = date_compact[:4] + "-" + date_compact[4:6] + "-" + date_compact[6:8]
            return {
                "race_id": race_id,
                "date": date_iso,
                "track_cd": track_cd,
                "race_nb": race_nb,
                "race_number": race_nb,
                "venue": _venue_name(track_cd),
                "surface": payload.get("surface", "ダート"),
                "distance": payload.get("distance", 0),
                "start_at": (date_iso + "T" + start_hhmm + ":00") if date_iso else "",
                "start_hhmm": start_hhmm,
                "runners": payload.get("runners", []),
                "source": "prefetched",
            }
    except Exception as exc:
        print("[races.detail] prefetch lookup error: " + repr(exc), flush=True)
    return {"error": "not found"}
