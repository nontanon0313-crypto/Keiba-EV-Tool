"""ent1 テーブルの各セルの class / rowspan / テキストを全行分出力。"""
from bs4 import BeautifulSoup

with open("debug_html/probe_RaceList_do.html", encoding="utf-8") as f:
    html = f.read()
soup = BeautifulSoup(html, "html.parser")
ent = soup.select_one("table.ent1")
rows = ent.find_all("tr")
print(f"total rows: {len(rows)}")
for i, row in enumerate(rows):
    cells = row.find_all(["td", "th"])
    if not cells:
        continue
    print(f"\n--- row{i} n={len(cells)} ---")
    for j, c in enumerate(cells):
        cls = " ".join(c.get("class") or [])
        rs = c.get("rowspan")
        cs = c.get("colspan")
        txt = c.get_text(" ", strip=True)[:34]
        print(f"  [{j}] class='{cls}' rs={rs} cs={cs} txt='{txt}'")
