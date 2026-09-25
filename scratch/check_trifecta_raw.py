"""軸馬=4 の生HTMLを保存して実際の組数を確認。読み取り専用。"""
import os
import re
import time
from bs4 import BeautifulSoup
import httpx
import backend.scraper.oddspark_keiba as ok

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Mobile Safari/537.36",
    "Referer": "https://www.oddspark.com/keiba/",
}

date, track, sponsor, rn = "20230101", "43", "33", 1

os.makedirs("debug_html", exist_ok=True)
with httpx.Client(headers=HEADERS, timeout=25, follow_redirects=True) as c:
    c.get("https://www.oddspark.com/keiba/")
    time.sleep(1)
    for hn in [4, 7]:
        url = (f"https://www.oddspark.com/keiba/Odds.do?sponsorCd={sponsor}&opTrackCd={track}"
               f"&raceDy={date}&raceNb={rn}&viewType=0&betType=8"
               f"&horseNb={hn}&jikuNb=1")
        r = c.get(url)
        print(f"\n=== hn={hn} status={r.status_code} len={len(r.text)} ===")
        fname = f"debug_html/trifecta_hn{hn}.html"
        with open(fname, "w", encoding="utf-8") as f:
            f.write(r.text)
        print(f"  saved: {fname}")

        # パーサー結果
        parsed = ok.parse_trifecta(r.text)
        print(f"  parse_trifecta: {len(parsed)} 組")

        # 生HTMLからオッズらしき数値を数える
        soup = BeautifulSoup(r.text, "html.parser")
        # table 全行
        tables = soup.find_all("table")
        print(f"  tables: {len(tables)}")
        for i, tb in enumerate(tables):
            rows = tb.find_all("tr")
            print(f"    table[{i}] class={tb.get('class')} rows={len(rows)}")

        # 'odds' or 'オッズ' を数える
        cells = soup.find_all(["td", "th"])
        print(f"  td/th cells: {len(cells)}")
        # 数値セルの数
        nums = re.findall(r'>\s*([\d.]+)\s*<', r.text)
        print(f"  数値パターン: {len(nums)}")
        # "1-2-3" 形式のキー数を数える
        keys = re.findall(r'\b(\d+-\d+-\d+)\b', r.text)
        print(f"  X-Y-Z キー: {len(set(keys))} unique / {len(keys)} total")

        # サンプルキー
        print(f"  sample keys: {sorted(set(keys))[:10]}")
        time.sleep(1.5)
