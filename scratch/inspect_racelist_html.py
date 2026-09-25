"""RaceList.do の実際のHTML構造を確認。読み取り専用。"""
import re
from bs4 import BeautifulSoup

path = "debug_html/probe_RaceList_do.html"
with open(path, encoding="utf-8") as f:
    html = f.read()

soup = BeautifulSoup(html, "html.parser")

print("=== title ===")
t = soup.find("title")
print(f"  {t.get_text(strip=True) if t else '(なし)'}")

print("\n=== ent1 テーブル ===")
ent = soup.select_one("table.ent1")
if ent is None:
    print("  [NG] table.ent1 が見つからない")
else:
    rows = ent.find_all("tr")
    print(f"  rows: {len(rows)}")
    for ri, row in enumerate(rows):
        cells = row.find_all(["td", "th"])
        if not cells:
            continue
        n = len(cells)
        texts = []
        spans = []
        for c in cells:
            txt = c.get_text(" ", strip=True)
            texts.append(txt[:18] if txt else "·")
            rs = c.get("rowspan")
            cs = c.get("colspan")
            sp = ""
            if rs: sp += f"r{rs}"
            if cs: sp += f"c{cs}"
            spans.append(sp)
        print(f"  row{ri} n={n}")
        print(f"    texts: {texts}")
        print(f"    spans: {spans}")

print("\n=== minipay テーブル群 ===")
for i, tbl in enumerate(soup.select("table.minipay")):
    rows = tbl.find_all("tr")
    print(f"  minipay[{i}] rows={len(rows)}")
    for ri, row in enumerate(rows[:4]):
        cells = row.find_all(["td", "th"])
        texts = [c.get_text(" ", strip=True)[:24] for c in cells]
        print(f"    r{ri}: {texts}")

print("\n=== 馬名を含む全テーブルのクラス ===")
for i, tbl in enumerate(soup.find_all("table")):
    txt = tbl.get_text(" ", strip=True)
    if "フークサプライズ" in txt or "スズカソブリン" in txt:
        print(f"  [{i}] class={tbl.get('class')} rows={len(tbl.find_all('tr'))}")

print("\n=== 'minipay' を含むクラスのテーブル数 ===")
print(f"  {len(soup.select('table.minipay'))}")

print("\n=== '払戻' 前後のテキスト ===")
body = soup.get_text(" ", strip=True)
idx = body.find("払戻")
if idx >= 0:
    print(f"  {body[max(0,idx-50):idx+400]}")
else:
    print("  '払戻' が見つからない")
