"""段階1: 天候・馬場を5レースで試行。payloadに追加する。"""
import os
import json
import re
import time
import httpx
import libsql_client

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Mobile Safari/537.36",
    "Referer": "https://www.oddspark.com/keiba/",
}

WEATHER_MAP = {"1": "晴", "2": "曇", "3": "不明", "4": "雨"}
BABA_MAP = {"1": "良", "2": "稍重", "3": "重", "4": "不良"}

# 帯広除外
EXCLUDED_TRACK_CODES = ("03",)


def parse_race_condition(html):
    m1 = re.search(r"ico-tenki-(\d+)\.gif", html)
    m2 = re.search(r"ico-baba-(\d+)\.gif", html)
    weather = WEATHER_MAP.get(m1.group(1), "不明") if m1 else "不明"
    baba = BABA_MAP.get(m2.group(1), "不明") if m2 else "不明"
    return weather, baba


def main():
    url = os.getenv("TURSO_URL")
    token = os.getenv("TURSO_TOKEN")
    http_url = url.replace("libsql://", "https://").replace("wss://", "https://")
    client = libsql_client.create_client_sync(url=http_url, auth_token=token)

    # 5レース取得（帯広除外）
    r = client.execute("SELECT race_id, payload FROM scraped_races ORDER BY race_id LIMIT 200")
    rows = list(r.rows)
    targets = []
    for row in rows:
        rid = row[0]
        parts = rid.split("-")
        if len(parts) >= 3 and parts[2] in EXCLUDED_TRACK_CODES:
            continue
        targets.append((rid, row[1]))
        if len(targets) >= 5:
            break

    print(f"対象: {len(targets)} レース\n")

    with httpx.Client(headers=HEADERS, timeout=25, follow_redirects=True) as c:
        c.get("https://www.oddspark.com/keiba/")
        time.sleep(1)
        for rid, payload_str in targets:
            payload = json.loads(payload_str)
            date = payload.get("date", "").replace("-", "")
            track_cd = payload.get("track_cd", "")
            sponsor_cd = payload.get("sponsor_cd", "")
            race_nb = payload.get("race_nb", 0)
            url2 = (f"https://www.oddspark.com/keiba/RaceResult.do"
                    f"?sponsorCd={sponsor_cd}&raceDy={date}"
                    f"&opTrackCd={track_cd}&raceNb={race_nb}")
            try:
                r2 = c.get(url2)
                if r2.status_code != 200:
                    print(f"  [{rid}] status={r2.status_code}")
                    continue
                weather, baba = parse_race_condition(r2.text)
                # payload に追加
                payload["weather"] = weather
                payload["track_condition"] = baba
                new_payload = json.dumps(payload, ensure_ascii=False)
                client.execute(
                    "UPDATE scraped_races SET payload=? WHERE race_id=?",
                    [new_payload, rid],
                )
                print(f"  [{rid}] weather={weather} track_condition={baba} 保存OK")
            except Exception as e:
                print(f"  [{rid}] ERROR: {e}")
            time.sleep(1.2)

    # 確認
    print("\n=== 確認 ===")
    for rid, _ in targets:
        r3 = client.execute("SELECT payload FROM scraped_races WHERE race_id=?", [rid])
        p = json.loads(list(r3.rows)[0][0])
        print(f"  [{rid}] weather={p.get('weather')} track_condition={p.get('track_condition')} "
              f"runners={len(p.get('runners', []))} result_runners={len(p.get('result_runners', []))}")

    try:
        client.close()
    except Exception:
        pass


main()
import os as _o
_o._exit(0)
