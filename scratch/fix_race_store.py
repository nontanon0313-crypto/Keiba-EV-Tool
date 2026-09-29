import io
p = "backend/app/services/race_store.py"
with io.open(p, encoding="utf-8") as f:
    src = f.read()

# 1) _Turso.__init__
old1 = '    def __init__(self, url, token):\n        import libsql_client\n        http_url = url.replace("libsql://", "https://").replace("wss://", "https://")\n        self.client = libsql_client.create_client_sync(url=http_url, auth_token=token)\n'
new1 = '    def __init__(self):\n        from backend.app.services import turso_client\n        client, err = turso_client.get_client()\n        if client is None:\n            raise RuntimeError("turso_client: " + str(err))\n        self.client = client\n'
if old1 in src:
    src = src.replace(old1, new1, 1)
    print("[OK] _Turso.__init__")
else:
    print("[NG] _Turso.__init__")

# 2) close メソッド
old2 = '    def close(self):\n        try:\n            self.client.close()\n        except Exception:\n            pass\n'
new2 = '    def close(self):\n        # 共有クライアントは閉じない\n        pass\n'
if old2 in src:
    src = src.replace(old2, new2, 1)
    print("[OK] close")
else:
    print("[NG] close")

# 3) _get() 呼び出し
old3 = '            _backend = _Turso(u, t)\n'
new3 = '            _backend = _Turso()\n'
if old3 in src:
    src = src.replace(old3, new3, 1)
    print("[OK] _get()")
else:
    print("[NG] _get()")

# 4) atexit 削除
old4 = 'atexit.register(close_race_store)\n'
new4 = '# atexit は使わない（main.py の shutdown で一括クリーンアップする）\n'
if old4 in src:
    src = src.replace(old4, new4, 1)
    print("[OK] atexit")
else:
    print("[NG] atexit")

with io.open(p, "w", encoding="utf-8") as f:
    f.write(src)
import os
os._exit(0)
