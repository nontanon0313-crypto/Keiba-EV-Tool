"""結果取得。MockAdapter 経由。JRA-VAN 接続時はここを差し替える。"""
from backend.app.services.race_fetcher import get_result as _mock_result


def fetch_result(race_id, num_runners=18, prediction=None):
    """予想に依存しない独立した結果を返す。
    prediction 引数は互換のため受け取るが使用しない。"""
    return _mock_result(race_id, num_runners)
