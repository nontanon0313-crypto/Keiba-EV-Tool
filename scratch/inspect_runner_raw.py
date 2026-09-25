"""読み取り専用: 馬番欠落レースのpayloadと生HTMLを突合。"""
import os
import json

import libsql_client
import httpx

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Mobile Safari/537.36",
    "Referer": "https://www.oddspark.com/keiba/",
}


def main():
    url = os.getenv("TURSO_URL")
    token = os.getenv("TURSO_TOKEN")
    http_url = url.replace("libsql://", "https://").replace("wss://", "https://")
    client = libsql_client.create_client_sync(url=http_url, auth_token=token)

    rid = "nar-20230101-43-1"
    r = client.execute("SELECT payload FROM scraped_races WHERE race_id = ?", [rid])
    rows = list(r.rows)
    if not rows:
        print(f"[NG] {rid} not found")
        return
    p = json.loads(rows[0][0])
    runners = p.get("runners", [])
    print(f"=== payload runners ({len(runners)}) ===")
    for r0 in runners:
        print(f"  num={r0.get('horse_number')} frame={r0.get('frame_number')} "
              f"name={r0.get('horse_name')} weight={r0.get('horse_weight')} "
              f"odds={r0.get('odds_win')} pop={r0.get('popularity')}")
    print(f"\n=== payload keys ===")
    print(list(p.keys()))
    print(f"\n=== result_runners ({len(p.get('result_runners', []))}) ===")
    for r0 in p.get("result_runners", [])[:20]:
        print(f"  {r0}")
    print(f"\n=== finish_order ===")
    print(p.get("finish_order"))

    # 生HTML取得（shutuba）
    date = "20230101"
    track_cd = "43"
    sponsor_cd = "43"
    race_nb = 1
    shutuba_url = f"https://www.oddspark.com/keiba/Shutuba.do?raceDy={date}&opTrackCd={track_cd}&sponsorCd={sponsor_cd}&raceNb={race_nb}"
    print(f"\n=== 生HTML取得: {shutuba_url} ===")
    try:
        r2 = httpx.get(shutuba_url, headers=HEADERS, timeout=20, follow_redirects=True)
        print(f"  status={r2.status_code} len={len(r2.text)}")
        os.makedirs("debug_html", exist_ok=True)
        with open(f"debug_html/shutuba_{rid}.html", "w", encoding="utf-8") as f:
            f.write(r2.text)
        print(f"  saved: debug_html/shutuba_{rid}.html")
        # 馬番らしきものだけ抜き出す
        import re
        nums = re.findall(r'<td[^>]*class="[^"]*num[^"]*"[^>]*>\s*(\d+)\s*</td>', r2.text)
        print(f"  td.num extracted: {nums[:30]}")
        # 馬名セル
        names = re.findall(r'<td[^>]*class="[^"]*horse[^"]*"[^>]*>\s*([^<]+)', r2.text)
        print(f"  horse cells: {names[:30]}")
    except Exception as e:
        print(f"  ERROR: {e}")

    try:
        client.close()
    except Exception:
        pass


main()
import os
os._exit(0)
