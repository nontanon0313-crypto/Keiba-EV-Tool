"""scraped_races / scraped_odds / analytics_cache を全削除。"""
import os
import libsql_client

url = os.getenv("TURSO_URL")
token = os.getenv("TURSO_TOKEN")
http_url = url.replace("libsql://", "https://").replace("wss://", "https://")
client = libsql_client.create_client_sync(url=http_url, auth_token=token)
for t in ("scraped_races", "scraped_odds", "analytics_cache"):
    try:
        client.execute(f"DELETE FROM {t}")
        n = client.execute(f"SELECT COUNT(*) FROM {t}").rows[0][0]
        print(f"{t}: after={n}")
    except Exception as e:
        print(f"{t}: {e}")
try:
    client.close()
except Exception:
    pass
import os as _o
_o._exit(0)
