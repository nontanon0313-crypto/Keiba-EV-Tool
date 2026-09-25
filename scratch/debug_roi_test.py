"""ROI計算不可の原因を切り分け。"""
import os
import json
import time
import httpx
import libsql_client
import backend.scraper.oddspark_keiba as ok

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Mobile Safari/537.36",
    "Referer": "https://www.oddspark.com/keiba/",
}

url = os.getenv("TURSO_URL")
token = os.getenv("TURSO_TOKEN")
http_url = url.replace("libsql://", "https://").replace("wss://", "https://")
client = libsql_client.create_client_sync(url=http_url, auth_token=token)

# まず1件
rid = "nar-20230101-43-1"
r = client.execute("SELECT payload FROM scraped_races WHERE race_id=?", [rid])
rows = list(r.rows)
print(f"DB rows: {len(rows)}")
p = json.loads(rows[0][0])
print(f"payload keys: {list(p.keys())}")
print(f"result_runners: {len(p.get('result_runners', []))}")
print(f"payouts keys: {list((p.get('payouts') or {}).keys())}")

with httpx.Client(headers=HEADERS, timeout=25, follow_redirects=True) as c:
    c.get("https://www.oddspark.com/keiba/")
    time.sleep(1)
    url2 = "https://www.oddspark.com/keiba/RaceResult.do?sponsorCd=33&raceDy=20230101&opTrackCd=43&raceNb=1"
    resp = c.get(url2)
    print(f"\nHTTP status={resp.status_code} len={len(resp.text)}")
    parsed = ok.parse_result(resp.text, rid)
    print(f"parse_result: {type(parsed)}")
    if parsed:
        print(f"  parsed keys: {list(parsed.keys())}")
        print(f"  result_runners: {len(parsed.get('result_runners', []))}")
        po = parsed.get("payouts", {})
        print(f"  payouts keys: {list(po.keys())}")
        for k, v in po.items():
            print(f"    {k}: {json.dumps(v, ensure_ascii=False)[:200]}")

try:
    client.close()
except Exception:
    pass
