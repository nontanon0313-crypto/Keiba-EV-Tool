"""1レース分の保存オッズと生ページの組数を突合。読み取り専用。"""
import os
import json
import time
from bs4 import BeautifulSoup
import httpx
import libsql_client

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Mobile Safari/537.36",
    "Referer": "https://www.oddspark.com/keiba/",
}

# 生ページのオッズを取得
def fetch_odds_live(client, date, track, sponsor, race_nb, bet_type):
    url = (f"https://www.oddspark.com/keiba/Odds.do?sponsorCd={sponsor}&opTrackCd={track}"
           f"&raceDy={date}&raceNb={race_nb}&viewType=0&betType={bet_type}")
    r = client.get(url)
    if r.status_code != 200:
        return None
    return r.text


def count_live_combos(html, parser):
    return parser(html) if html else {}


def main():
    url = os.getenv("TURSO_URL")
    token = os.getenv("TURSO_TOKEN")
    http_url = url.replace("libsql://", "https://").replace("wss://", "https://")
    client = libsql_client.create_client_sync(url=http_url, auth_token=token)

    rid = "nar-20230101-43-1"
    r = client.execute("SELECT payload FROM scraped_odds WHERE race_id=?", [rid])
    rows = list(r.rows)
    if not rows:
        print(f"[NG] {rid} not found in scraped_odds")
        return
    saved = json.loads(rows[0][0])
    print(f"=== 保存 odds payload: {rid} ===")
    for k, v in saved.items():
        if isinstance(v, dict):
            print(f"  {k}: {len(v)} 組")

    # 生ページから再取得
    import backend.scraper.oddspark_keiba as ok
    print("\n=== 生ページから再取得 ===")
    with httpx.Client(headers=HEADERS, timeout=25, follow_redirects=True) as c:
        c.get("https://www.oddspark.com/keiba/")
        time.sleep(1)
        date, track, sponsor, rn = "20230101", "43", "33", 1
        checks = [
            ("quinella", "6", ok.parse_quinella),
            ("wide",     "7", ok.parse_wide),
            ("exacta",   "5", ok.parse_exacta),
            ("trio",     "9", ok.parse_trio),
        ]
        for name, bt, parser in checks:
            html = fetch_odds_live(c, date, track, sponsor, rn, bt)
            live = parser(html) if html else {}
            print(f"  {name}: live={len(live)} 組")
            time.sleep(1.2)

    try:
        client.close()
    except Exception:
        pass


main()
import os
os._exit(0)
