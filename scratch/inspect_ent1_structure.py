"""読み取り専用: 保存済みHTMLのtable.ent1各行のセル構成を確認。"""
import os
from bs4 import BeautifulSoup

path = "debug_html/shutuba_nar-20230101-43-1.html"
if not os.path.exists(path):
    print(f"[NG] {path} が無い")
    raise SystemExit

with open(path, encoding="utf-8") as f:
    html = f.read()

soup = BeautifulSoup(html, "html.parser")
table = soup.select_one("table.ent1")
if table is None:
    print("[NG] table.ent1 が無い")
    tables = soup.find_all("table")
    print(f"  tables in page: {len(tables)}")
    for i, t in enumerate(tables[:5]):
        cls = t.get("class")
        print(f"    [{i}] class={cls} rows={len(t.find_all('tr'))}")
    raise SystemExit

print("=== table.ent1 rows ===")
for ri, row in enumerate(table.find_all("tr")):
    cells = row.find_all(["td", "th"])
    if not cells:
        continue
    n = len(cells)
    texts = []
    for c in cells:
        t = c.get_text(" ", strip=True)
        texts.append(t[:14])
    print(f"  row{ri}: n={n} cells={texts}")

print("\n=== 全tableのクラス ===")
for i, t in enumerate(soup.find_all("table")):
    print(f"  [{i}] class={t.get('class')} rows={len(t.find_all('tr'))}")
