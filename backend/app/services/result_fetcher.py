"""結果取得。Turso の実レース payload から finish_order を取得。"""
from backend.app.services import race_store


def fetch_result(race_id, num_runners=18, prediction=None):
    """race_store の payload.finish_order を返す。なければ None。"""
    p = race_store.get_race(race_id)
    if not p:
        return None
    order = p.get("finish_order")
    if not order:
        return None
    return list(order)
