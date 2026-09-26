"""analytics_cache の ticket_stats を全フィールド表示。"""
import os, json
import libsql_client

url = os.getenv("TURSO_URL")
token = os.getenv("TURSO_TOKEN")
http_url = url.replace("libsql://", "https://").replace("wss://", "https://")
client = libsql_client.create_client_sync(url=http_url, auth_token=token)
r = client.execute("SELECT payload, updated_at FROM analytics_cache WHERE id=1")
rows = list(r.rows)
p = json.loads(rows[0][0])
print(f"updated_at: {rows[0][1]}")
print(f"ticket_stats キー: {list(p['ticket_stats'][0].keys()) if p['ticket_stats'] else 'なし'}")
print()
for t in p.get("ticket_stats", []):
    print(f"  {t.get('label')}:")
    for k, v in t.items():
        print(f"    {k}: {v}")
try:
    client.close()
except Exception:
    pass
import os as _o
_o._exit(0)
