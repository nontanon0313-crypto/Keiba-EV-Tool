"""全ストアで共有する Turso クライアント。

各ストアが個別に create_client_sync すると、aiohttp の ClientSession が
複数作られ、close してもGCまで残る。これがメモリリークの原因になる。
このモジュールで1つのクライアントを共有し、プロセスあたり1セッションに抑える。
"""
import os

_client = None
_error = None


def get_client():
    """共有 Turso クライアントを返す。初回のみ作成。

    Returns: (client, error_message)
    """
    global _client, _error
    if _client is not None:
        return _client, None
    if _error is not None:
        return None, _error
    url = os.getenv("TURSO_URL")
    token = os.getenv("TURSO_TOKEN")
    if not url or not token:
        _error = "TURSO_URL/TURSO_TOKEN not set"
        return None, _error
    try:
        import libsql_client
    except ImportError:
        _error = "libsql_client not installed"
        return None, _error
    http_url = url.replace("libsql://", "https://").replace("wss://", "https://")
    try:
        _client = libsql_client.create_client_sync(url=http_url, auth_token=token)
        return _client, None
    except Exception as e:
        _error = str(e)
        return None, _error


def close_client():
    """アプリ終了時に呼ぶ。"""
    global _client, _error
    if _client is not None:
        try:
            _client.close()
        except Exception:
            pass
    _client = None
    _error = None


def has_client():
    return _client is not None
