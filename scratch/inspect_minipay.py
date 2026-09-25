"""結果ページの minipay テーブル構造を確定。"""
import time
import os
from bs4 import BeautifulSoup
import httpx

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Mobile Safari/537.36",
    "Referer": "https://www.oddspark.com/keiba/",
}

url = "https://www.oddspark.com/keiba/RaceResult.do?sponsorCd=33&raceDy=20230101&opTrackCd=43&raceNb=1"

with httpx.Client(headers=HEADERS, timeout=25, follow_redirects=True) as c:
    r = c.get(url)
    print(f"status={r.status_code} len={len(r.text)}")
    os.makedirs("debug_html", exist_ok=True)
    with open("debug_html/result_minipay_sample.html", "w", encoding="utf-8") as f:
        f.write(r.text)

soup = BeautifulSoup(r.text, "html.parser")

print("\n=== table 全クラス ===")
for i, tb in enumerate(soup.find_all("table")):
    txt = tb.get_text(" ", strip=True)
    print(f"  [{i}] class={tb.get('class')} id={tb.get('id')} rows={len(tb.find_all('tr'))} txt={txt[:100]}")

print("\n=== 'minipay' を含む要素 ===")
for el in soup.select("[class*='minipay']"):
    print(f"  tag={el.name} class={el.get('class')}")

print("\n=== 払戻テーブルの詳細 ===")
# 払戻テーブルを特定（'払戻' を含む table、または minipay）
target = None
for tb in soup.find_all("table"):
    if "払戻" in tb.get_text(" ", strip=True):
        target = tb
        break
if target:
    print(f"  target class={target.get('class')}")
    for ri, row in enumerate(target.find_all("tr")):
        cells = row.find_all(["td", "th"])
        if not cells:
            continue
        texts = []
        spans = []
        for c in cells:
            t = c.get_text(" ", strip=True)[:18]
            rs = c.get("rowspan")
            cs = c.get("colspan")
            sp = ""
            if rs: sp += f"r{rs}"
            if cs: sp += f"c{cs}"
            texts.append(t)
            spans.append(sp)
        print(f"  row{ri} n={len(cells)}")
        print(f"    texts: {texts}")
        print(f"    spans: {spans}")
else:
    print("  '払戻' を含む table が見つからない")
    print("  全 table の内 'minipay' クラスを持つものを探す")
    for tb in soup.select("table.minipay"):
        for ri, row in enumerate(tb.find_all("tr")):
            cells = row.find_all(["td", "th"])
            texts = [c.get_text(" ", strip=True)[:18] for c in cells]
            spans = [(c.get("rowspan"), c.get("colspan")) for c in cells]
            print(f"  row{ri}: texts={texts}")
            print(f"          spans={spans}")
