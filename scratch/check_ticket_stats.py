"""analytics_cache の ticket_stats に avg_odds が入っているか確認。"""
import os, json
import libsql_client

url = os.getenv("TURSO_URL")
token = os.getenv("TURSO_TOKEN")
http_url = url.replace("libsql://", "https://").replace("wss://", "https://")
client = libsql_client.create_client_sync(url=http_url, auth_token=token)
r = client.execute("SELECT payload, updated_at FROM analytics_cache WHERE id=1")
rows = list(r.rows)
if not rows:
    print("[NG] analytics_cache 空")
    raise SystemExit
p = json.loads(rows[0][0])
print(f"updated_at: {rows[0][1]}")
print(f"\n=== ticket_stats ===")
for t in p.get("ticket_stats", []):
    print(f"  {t.get('label')}: count={t.get('count')} avg_odds={t.get('avg_odds')} "
          f"exp_profit={t.get('expected_profit_pct')} act_profit={t.get('actual_profit_pct')}")
try:
    client.close()
except Exception:
    pass
import os as _o
_o._exit(0)
