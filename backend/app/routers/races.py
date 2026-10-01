from fastapi import APIRouter, HTTPException
from datetime import datetime
from backend.app.services.race_fetcher import get_races
from backend.app.services import entry_store

router = APIRouter(prefix="/races")


_prefetch_lock = None
_prefetch_state = {"running": False, "date": "", "started_at": ""}


def _ensure_lock():
    global _prefetch_lock
    import threading
    if _prefetch_lock is None:
        _prefetch_lock = threading.Lock()


def _run_prefetch_today():
    import asyncio
    from backend.scripts import prefetch_entries as pe
    _ensure_lock()
    with _prefetch_lock:
        if _prefetch_state["running"]:
            return
        _prefetch_state["running"] = True
        _prefetch_state["date"] = datetime.now().strftime("%Y%m%d")
        _prefetch_state["started_at"] = datetime.now().isoformat()
    try:
        asyncio.run(pe.main_async(0, False))
    except Exception as exc:
        print("[races.prefetch] error: " + repr(exc), flush=True)
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
            if not _prefetch_state["running"]:
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


@router.get("/{race_id}")
def get_race(race_id: str):
    for r in get_races():
        if r.race_id == race_id:
            return r
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
