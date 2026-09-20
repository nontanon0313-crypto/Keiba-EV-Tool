"""Result store (JSON file persisted)."""
import json
from pathlib import Path
from typing import Dict, List, Optional

STORE_PATH = Path("results.json")


def _load():
    if not STORE_PATH.exists():
        return {}
    try:
        return json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(data):
    STORE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def record_result(race_id, finish_order):
    data = _load()
    data[race_id] = [int(x) for x in finish_order]
    _save(data)
    return {"race_id": race_id, "finish_order": data[race_id]}


def get_result(race_id):
    return _load().get(race_id)


def all_results():
    return _load()
