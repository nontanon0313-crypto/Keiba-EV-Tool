"""全レースの天候・馬場を取得して payload に追加。

スキップ条件:
- 帯広(track_cd=03)
- 既に weather と track_condition が入っているレース

200レースごとに進捗を出力。
"""
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

    r = client.execute("SELECT race_id, payload FROM scraped_races ORDER BY race_id")
    rows = list(r.rows)
    print(f"全レース: {len(rows)}", flush=True)

    t0 = time.time()
    n_updated = 0
    n_skipped_exist = 0
    n_skipped_excl = 0
    n_failed = 0
    total = len(rows)

    with httpx.Client(headers=HEADERS, timeout=25, follow_redirects=True) as c:
        c.get("https://www.oddspark.com/keiba/")
        time.sleep(1)
        for idx, row in enumerate(rows):
            rid = row[0]
            parts = rid.split("-")
            if len(parts) >= 3 and parts[2] in EXCLUDED_TRACK_CODES:
                n_skipped_excl += 1
                continue
            try:
                payload = json.loads(row[1])
            except Exception:
                continue
            if payload.get("weather") and payload.get("track_condition"):
                n_skipped_exist += 1
                continue
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
                    n_failed += 1
                    continue
                weather, baba = parse_race_condition(r2.text)
                payload["weather"] = weather
                payload["track_condition"] = baba
                new_payload = json.dumps(payload, ensure_ascii=False)
                client.execute(
                    "UPDATE scraped_races SET payload=? WHERE race_id=?",
                    [new_payload, rid],
                )
                n_updated += 1
            except Exception as e:
                n_failed += 1
            time.sleep(1.0)
            if (idx + 1) % 200 == 0:
                elapsed = time.time() - t0
                remain = total - (idx + 1)
                rate = (idx + 1) / elapsed if elapsed > 0 else 0
                eta = remain / rate if rate > 0 else 0
                print(f"  {idx+1}/{total} updated={n_updated} skipped_exist={n_skipped_exist} "
                      f"excl={n_skipped_excl} failed={n_failed} "
                      f"elapsed={elapsed:.0f}s eta={eta:.0f}s", flush=True)

    elapsed = time.time() - t0
    print(f"\n=== 完了: updated={n_updated} skipped_exist={n_skipped_exist} "
          f"excl={n_skipped_excl} failed={n_failed} elapsed={elapsed:.0f}s ===", flush=True)

    try:
        client.close()
    except Exception:
        pass


main()
import os as _o
_o._exit(0)
