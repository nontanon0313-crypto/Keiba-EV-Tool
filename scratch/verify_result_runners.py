"""DB の result_runners を生ページと20件突合。読み取り専用。"""
import os
import re
import json
import time
from bs4 import BeautifulSoup
import httpx
import libsql_client

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Mobile Safari/537.36",
    "Referer": "https://www.oddspark.com/keiba/",
}

# 正しい sponsor を見つけるための候補（前回結果から）
SPONSOR_CANDIDATES = {
    "03": ["03"], "06": ["03"], "11": ["03"], "12": ["03"],
    "31": ["03"], "32": ["03"], "33": ["03"],
    "41": ["03"], "42": ["03"], "43": ["33", "03"],
    "51": ["03"], "52": ["03"], "55": ["29", "03"], "61": ["03"],
}


def parse_result_page(html):
    """結果ページから runners / finish_order / payouts を抽出。"""
    soup = BeautifulSoup(html, "html.parser")
    # 結果テーブルを特定
    table = None
    for tb in soup.find_all("table"):
        txt = tb.get_text(" ", strip=True)
        if "1着" in txt and "馬名" in txt:
            table = tb
            break
    if table is None:
        # 代替: 着順列がある table
        for tb in soup.find_all("table"):
            rows = tb.find_all("tr")
            if len(rows) >= 3:
                for r in rows[:3]:
                    cells = r.find_all(["td", "th"])
                    if len(cells) >= 8:
                        table = tb
                        break
                if table:
                    break
    runners = []
    finish_order = []
    if table:
        for row in table.find_all("tr")[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) < 8:
                continue
            def gi(i):
                try:
                    return int(re.sub(r"\D", "", cells[i].get_text(strip=True)) or 0)
                except Exception:
                    return None
            finish = gi(0)
            frame = gi(1)
            num = gi(2)
            if num is None:
                continue
            name = cells[3].get_text(strip=True)
            runners.append({
                "finish": finish, "frame_number": frame, "horse_number": num,
                "horse_name": name,
            })
            if finish and finish <= 3:
                finish_order.append((finish, num))
    finish_order.sort()
    return {
        "runners": runners,
        "finish_order": [n for _, n in finish_order],
    }


def fetch_result_page(client, date, track_cd, race_nb):
    for sp in SPONSOR_CANDIDATES.get(track_cd, ["03"]):
        url = f"https://www.oddspark.com/keiba/RaceResult.do?sponsorCd={sp}&raceDy={date}&opTrackCd={track_cd}&raceNb={race_nb}"
        try:
            r = client.get(url)
            if r.status_code == 200 and len(r.text) > 15000:
                return r.text, url
        except Exception:
            pass
        time.sleep(0.5)
    return None, None


def main():
    url = os.getenv("TURSO_URL")
    token = os.getenv("TURSO_TOKEN")
    http_url = url.replace("libsql://", "https://").replace("wss://", "https://")
    client = libsql_client.create_client_sync(url=http_url, auth_token=token)

    r = client.execute(
        "SELECT race_id, payload FROM scraped_races "
        "WHERE race_id LIKE 'nar-2023%' ORDER BY race_id LIMIT 200"
    )
    rows = list(r.rows)
    print(f"取得候補: {len(rows)}件（先頭200から20件抽出）")

    samples = []
    for row in rows:
        try:
            p = json.loads(row[1])
        except Exception:
            continue
        rr = p.get("result_runners", [])
        if rr and len(rr) >= 5:
            samples.append((row[0], p))
        if len(samples) >= 20:
            break

    print(f"突合対象: {len(samples)}件\n")

    ng_count = 0
    with httpx.Client(headers=HEADERS, timeout=25, follow_redirects=True) as c:
        c.get("https://www.oddspark.com/keiba/")
        time.sleep(1)
        for rid, p in samples:
            parts = rid.split("-")
            date, track, rn = parts[1], parts[2], parts[3]
            html, url_used = fetch_result_page(c, date, track, rn)
            db_rr = p.get("result_runners", [])
            db_fo = p.get("finish_order", [])

            if html is None:
                print(f"[{rid}] 生ページ取得失敗 (track={track})")
                ng_count += 1
                continue

            live = parse_result_page(html)

            db_nums = sorted([x.get("horse_number") for x in db_rr if x.get("horse_number")])
            live_nums = sorted([x.get("horse_number") for x in live["runners"]])

            db_names = {x.get("horse_number"): x.get("horse_name") for x in db_rr}
            live_names = {x.get("horse_number"): x.get("horse_name") for x in live["runners"]}

            num_match = db_nums == live_nums
            fo_match = db_fo == live["finish_order"]

            name_diffs = []
            for n in set(db_names) & set(live_names):
                if db_names[n] != live_names[n]:
                    name_diffs.append((n, db_names[n], live_names[n]))

            status = "OK" if (num_match and fo_match and not name_diffs) else "NG"
            if status == "NG":
                ng_count += 1
            print(f"[{rid}] {status} url={url_used}")
            print(f"   DB_nums={db_nums}")
            print(f"   live_nums={live_nums}")
            print(f"   DB_finish={db_fo} live_finish={live['finish_order']}")
            if name_diffs:
                print(f"   馬名差分({len(name_diffs)}): {name_diffs[:3]}")

    print(f"\n=== 結果: {len(samples)}件中 NG={ng_count} ===")
    try:
        client.close()
    except Exception:
        pass


main()
import os
os._exit(0)
